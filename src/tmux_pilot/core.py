"""Core tmux interaction: list, create, peek, send, kill, metadata."""

from __future__ import annotations

import json
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


def _tmux(*args: str, check: bool = True, timeout: int = 5) -> str:
    """Run a tmux command and return stdout stripped."""
    result = _run(["tmux", *args], check=check, timeout=timeout)
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

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON output."""
        return {
            "name": self.name,
            "process": self.process,
            "working_dir": self.working_dir,
            "metadata": dict(self.metadata),
        }


_META_FMT = "\t".join(f"#{{@{k}}}" for k in METADATA_KEYS)
_SESSION_FMT = f"#{{session_name}}\t#{{pane_current_command}}\t#{{pane_current_path}}\t{_META_FMT}"


def _parse_session_line(line: str) -> SessionInfo | None:
    """Parse a single tab-separated tmux format line into a SessionInfo."""
    parts = line.split("\t")
    if len(parts) < 3:
        return None

    name, pane_cmd, pane_path = parts[0], parts[1], parts[2]
    meta = {}
    for i, key in enumerate(METADATA_KEYS):
        val = parts[3 + i] if (3 + i) < len(parts) else ""
        if val:
            meta[key] = val

    return SessionInfo(
        name=name,
        process=_detect_process(pane_cmd),
        working_dir=pane_path,
        metadata=meta,
    )


def list_sessions(
    *,
    status: str | None = None,
    repo: str | None = None,
    process: str | None = None,
) -> list[SessionInfo]:
    """List all tmux sessions with metadata, with optional filters."""
    if not tmux_running():
        return []

    raw = _tmux("list-sessions", "-F", _SESSION_FMT, check=False)
    if not raw:
        return []

    sessions: list[SessionInfo] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        info = _parse_session_line(line)
        if info is None or info.name in seen:
            continue
        seen.add(info.name)

        if status and info.status.lower() != status.lower():
            continue
        if process and info.process.lower() != process.lower():
            continue
        if repo and repo.lower() not in info.repo.lower() and repo.lower() not in info.name.lower():
            continue

        sessions.append(info)
    return sessions


def get_metadata(session_name: str, key: str) -> str:
    """Get a single @metadata value from a session using display-message."""
    return _tmux("display-message", "-t", session_name, "-p", f"#{{@{key}}}", check=False)


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


def peek_session(name: str, lines: int = 50, timeout: int = 3) -> str:
    """Capture last N lines of scrollback from a session without attaching."""
    return _tmux("capture-pane", "-t", name, "-p", "-S", f"-{lines}", check=True, timeout=timeout)


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


def _attach_or_switch(target: str) -> None:
    """Attach or switch to a session by exact name."""
    if _is_inside_tmux():
        _tmux("switch-client", "-t", target)
    else:
        result = _run(["tmux", "attach-session", "-t", target], check=False, capture=False)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to attach to session '{target}'")


def _resolve_session(name: str) -> str:
    """Resolve a name to an exact session, supporting substring matching.

    - Exact match: return immediately.
    - Single substring match: return that session.
    - Multiple substring matches: raise with list of matches.
    - No matches: raise.
    """
    sessions = list_sessions()
    exact = [s for s in sessions if s.name == name]
    if exact:
        return exact[0].name

    matches = [s for s in sessions if name.lower() in s.name.lower()]

    if len(matches) == 1:
        return matches[0].name
    if len(matches) > 1:
        names = ", ".join(s.name for s in matches)
        raise RuntimeError(f"'{name}' matches multiple sessions: {names}")
    raise RuntimeError(f"No session matching '{name}'")


def jump_session(name: str | None = None) -> None:
    """Attach or switch to a session. Supports substring matching and fzf picker."""
    if name:
        target = _resolve_session(name)
        _attach_or_switch(target)
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
    _attach_or_switch(chosen)


def _is_inside_tmux() -> bool:
    """Check if we're currently inside a tmux session."""
    import os
    return "TMUX" in os.environ


def get_session_status(name: str) -> dict:
    """Get detailed status for a session using batched format strings."""
    if not session_exists(name):
        raise RuntimeError(f"Session '{name}' not found")

    # Fetch pane info + all metadata in one call
    pane_fmt = (
        "#{pane_current_command}\t#{pane_current_path}\t#{pane_pid}\t"
        + _META_FMT
    )
    raw = _tmux("list-panes", "-t", name, "-F", pane_fmt)
    parts = raw.splitlines()[0].split("\t") if raw else []

    pane_cmd = parts[0] if len(parts) > 0 else ""
    pane_path = parts[1] if len(parts) > 1 else ""
    pane_pid = parts[2] if len(parts) > 2 else ""

    meta = {}
    for i, key in enumerate(METADATA_KEYS):
        val = parts[3 + i] if (3 + i) < len(parts) else ""
        if val:
            meta[key] = val

    scrollback = peek_session(name, lines=5)

    return {
        "name": name,
        "process": _detect_process(pane_cmd),
        "pid": pane_pid,
        "working_dir": pane_path,
        "metadata": meta,
        "scrollback_tail": scrollback,
    }
