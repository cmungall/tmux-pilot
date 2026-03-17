"""Core tmux interaction: list, create, peek, send, kill, metadata."""

from __future__ import annotations

import subprocess
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# Metadata keys stored as tmux user options (@-prefixed)
METADATA_KEYS = ("repo", "task", "desc", "status", "origin", "branch", "needs")

# Map pane_current_command to friendly process names
PROCESS_ALIASES: dict[str, str] = {
    "claude": "claude-code",
    "node": "claude-code",  # claude-code runs as node
    "codex": "codex",
    "python": "python",
    "zsh": "zsh",
    "bash": "bash",
    "fish": "fish",
}

# Claude Code reports its version as pane_current_command (e.g. "2.1.76")
import re
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _run(
    args: list[str],
    *,
    check: bool = True,
    capture: bool = True,
    timeout: int = 5,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess, returning CompletedProcess."""
    try:
        return subprocess.run(
            args,
            capture_output=capture,
            text=True,
            check=check,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="timeout")


def _tmux(*args: str, check: bool = True) -> str:
    """Run a tmux command and return stdout stripped."""
    result = _run(["tmux", *args], check=check)
    return result.stdout.strip() if result.stdout else ""


def tmux_running() -> bool:
    """Check if tmux server is running."""
    result = _run(["tmux", "list-sessions"], check=False)
    return result.returncode == 0


def _detect_process(pane_cmd: str) -> str:
    """Map a pane_current_command to a friendly name."""
    cmd = pane_cmd.strip()
    # Claude Code reports its version number as the command (e.g. "2.1.76")
    if _VERSION_RE.match(cmd):
        return "claude-code"
    cmd_lower = cmd.lower()
    for key, alias in PROCESS_ALIASES.items():
        if key in cmd_lower:
            return alias
    return cmd or "unknown"


@dataclass
class SessionInfo:
    """Metadata about a tmux session."""

    name: str
    process: str = "unknown"
    working_dir: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return self.metadata.get("status", "")

    @property
    def desc(self) -> str:
        return self.metadata.get("desc", "")

    @property
    def repo(self) -> str:
        return self.metadata.get("repo", "")


def list_sessions() -> list[SessionInfo]:
    """List all tmux sessions with metadata."""
    if not tmux_running():
        return []

    # Fetch everything in one tmux call including @-prefixed metadata
    fmt = (
        "#{session_name}\t#{pane_current_command}\t#{pane_current_path}\t"
        "#{@repo}\t#{@task}\t#{@desc}\t#{@status}\t#{@origin}\t#{@branch}\t#{@needs}"
    )
    raw = _tmux("list-sessions", "-F", fmt, check=False)
    if not raw:
        return []

    sessions: list[SessionInfo] = []
    seen: set[str] = set()
    meta_keys = ("repo", "task", "desc", "status", "origin", "branch", "needs")
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        name, pane_cmd, pane_path = parts[0], parts[1], parts[2]
        if name in seen:
            continue
        seen.add(name)

        meta = {}
        for i, key in enumerate(meta_keys):
            val = parts[3 + i] if (3 + i) < len(parts) else ""
            if val:
                meta[key] = val

        sessions.append(
            SessionInfo(
                name=name,
                process=_detect_process(pane_cmd),
                working_dir=pane_path,
                metadata=meta,
            )
        )
    return sessions


def _get_all_metadata(session_name: str) -> dict[str, str]:
    """Read all @-prefixed user options from a session in one call."""
    result = _run(
        ["tmux", "show-options", "-t", session_name],
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        return {}
    meta: dict[str, str] = {}
    for line in result.stdout.strip().splitlines():
        if not line.startswith("@"):
            continue
        parts = line.split(" ", 1)
        if len(parts) == 2:
            key = parts[0][1:]  # strip @
            val = parts[1].strip().strip('"')
            meta[key] = val
    return meta


def get_metadata(session_name: str, key: str) -> str:
    """Get a single @metadata value from a session."""
    result = _run(
        ["tmux", "show-options", "-t", session_name, "-v", f"@{key}"],
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def set_metadata(session_name: str, key: str, value: str) -> None:
    """Set a @metadata value on a session."""
    _tmux("set-option", "-t", session_name, f"@{key}", value)


def new_session(
    name: str,
    *,
    directory: str | None = None,
    desc: str | None = None,
) -> None:
    """Create a new detached tmux session with optional metadata."""
    cmd = ["tmux", "new-session", "-d", "-s", name]
    if directory:
        p = Path(directory).expanduser().resolve()
        cmd.extend(["-c", str(p)])
    _run(cmd, check=True)

    if desc:
        set_metadata(name, "desc", desc)
    if directory:
        set_metadata(name, "repo", str(Path(directory).expanduser().resolve()))


def peek_session(name: str, lines: int = 50) -> str:
    """Capture last N lines of scrollback from a session without attaching."""
    return _tmux("capture-pane", "-t", name, "-p", "-S", f"-{lines}", check=True)


def send_keys(name: str, text: str) -> None:
    """Send text + Enter to a session's active pane."""
    _tmux("send-keys", "-t", name, text, "Enter")


def kill_session(name: str) -> None:
    """Kill a tmux session."""
    _tmux("kill-session", "-t", name)


def session_exists(name: str) -> bool:
    """Check if a session with the given name exists."""
    result = _run(["tmux", "has-session", "-t", name], check=False)
    return result.returncode == 0


def jump_session(name: str | None = None) -> None:
    """Attach or switch to a session. If no name, use fzf picker."""
    if name:
        # If inside tmux, switch; otherwise attach
        if _is_inside_tmux():
            _tmux("switch-client", "-t", name)
        else:
            subprocess.run(["tmux", "attach-session", "-t", name], check=True)
        return

    # fzf picker
    if not shutil.which("fzf"):
        raise RuntimeError("fzf not found — install it or specify a session name")

    sessions = list_sessions()
    if not sessions:
        raise RuntimeError("No tmux sessions found")

    lines = []
    for s in sessions:
        label = f"{s.name}  [{s.process}]"
        if s.desc:
            label += f"  {s.desc}"
        lines.append(label)

    fzf_input = "\n".join(lines)
    result = subprocess.run(
        ["fzf", "--height=40%", "--reverse", "--prompt=session> "],
        input=fzf_input,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return  # user cancelled
    chosen = result.stdout.strip().split()[0]
    jump_session(chosen)


def _is_inside_tmux() -> bool:
    """Check if we're currently inside a tmux session."""
    import os
    return "TMUX" in os.environ


def get_session_status(name: str) -> dict:
    """Get detailed status for a session."""
    if not session_exists(name):
        raise RuntimeError(f"Session '{name}' not found")

    fmt = "#{pane_current_command}\t#{pane_current_path}\t#{pane_pid}"
    raw = _tmux("list-panes", "-t", name, "-F", fmt)
    parts = raw.splitlines()[0].split("\t", 2) if raw else ["", "", ""]
    pane_cmd = parts[0] if len(parts) > 0 else ""
    pane_path = parts[1] if len(parts) > 1 else ""
    pane_pid = parts[2] if len(parts) > 2 else ""

    meta = _get_all_metadata(name)
    scrollback = peek_session(name, lines=20)

    return {
        "name": name,
        "process": _detect_process(pane_cmd),
        "pid": pane_pid,
        "working_dir": pane_path,
        "metadata": meta,
        "scrollback_tail": scrollback,
    }
