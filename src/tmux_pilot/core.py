"""Core tmux interaction: list, create, peek, send, kill, metadata."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:
    import tomllib  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib  # type: ignore[import-not-found]

# Metadata keys stored as tmux user options (@-prefixed)
METADATA_KEYS = (
    "repo",
    "task",
    "desc",
    "status",
    "origin",
    "branch",
    "needs",
    "last_commit",
    "last_send",
    "pr",
    "pr_state",
    "pr_review",
    "pr_merge_state",
    "last_refresh",
    "pushing",
)

# Map pane_current_command to friendly process names
PROCESS_ALIASES: dict[str, str] = {
    "claude": "claude-code",
    "codex": "codex",
    "pi": "pi",
    "python": "python",
    "zsh": "zsh",
    "bash": "bash",
    "fish": "fish",
}

# When pane_current_command is "node", we need to disambiguate:
# Claude Code runs as node, but so does Codex.
NODE_DISAMBIGUATION: dict[str, str] = {
    "codex": "codex",
    "claude": "claude-code",
    "openai": "codex",
}

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
PROFILE_CONFIG_PATH = Path.home() / ".config" / "tmux-pilot" / "profiles.toml"
_DEFAULT_CLONE_BASE = "~/repos"
_DEFAULT_WORKTREE_BASE = "~/worktrees"
_SEND_KEYS_SETTLE_DELAY = 0.1
_CWD_VERIFY_TIMEOUT = 2.0
_CWD_VERIFY_INTERVAL = 0.05
_PI_SESSION_DIR_TEMPLATE = "{worktree}/.tmux-pilot/pi/sessions"
_BUILTIN_PROFILE_DEFS: dict[str, dict[str, object]] = {
    "codex": {
        "command": ["codex", "--profile", "yolo"],
        "prompt_wait_timeout": 10.0,
    },
    "claude": {
        "command": ["claude", "--permission-mode", "bypassPermissions"],
        "prompt_wait_timeout": 10.0,
    },
    "pi": {
        "command": [
            "pi",
            "--offline",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-themes",
            "--session-dir",
            _PI_SESSION_DIR_TEMPLATE,
        ],
        "prompt_wait_timeout": 5.0,
    },
}
_GITHUB_REPO_RE = re.compile(
    r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/|github\.com/)?"
    r"(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?/?$"
)


@dataclass
class SessionProfile:
    """Resolved project profile for `tp new --profile`."""

    name: str
    extends: str = ""
    repo: str = ""
    agent: str = ""
    agent_args: str = ""
    command: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    clone_base: str = _DEFAULT_CLONE_BASE
    worktree_base: str = _DEFAULT_WORKTREE_BASE
    branch_prefix: str = ""
    base_ref: str = ""
    prompt_wait_timeout: float = 10.0

    @property
    def command_parts(self) -> tuple[str, ...]:
        if self.command:
            return self.command
        parts = [self.agent.strip(), *shlex.split(self.agent_args)]
        return tuple(part for part in parts if part)


def _run(
    args: list[str],
    *,
    check: bool = True,
    capture: bool = True,
    cwd: str | None = None,
    timeout: int = 5,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess, returning CompletedProcess."""
    try:
        return subprocess.run(
            args,
            capture_output=capture,
            text=True,
            check=check,
            cwd=cwd,
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


def _child_pids(pid: str) -> list[str]:
    """Return child process IDs for *pid*."""
    if not pid:
        return []
    result = _run(["pgrep", "-P", pid], check=False, timeout=3)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _raw_process_command_line(pid: str = "") -> str:
    if not pid:
        return ""
    result = _run(["ps", "-o", "command=", "-p", pid], check=False, timeout=3)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _process_command_line(pane_pid: str = "") -> str:
    """Return the foreground-ish command line for a pane."""
    current_pid = pane_pid
    command_line = _raw_process_command_line(current_pid)

    while command_line:
        base = Path(command_line.split()[0]).name.lower().lstrip("-")
        if base not in {"zsh", "bash", "fish", "sh"}:
            return command_line

        children = _child_pids(current_pid)
        if not children:
            return command_line
        current_pid = children[-1]
        command_line = _raw_process_command_line(current_pid)

    return ""


def _detect_process(pane_cmd: str, session_name: str = "", pane_pid: str = "") -> str:
    """Map a pane_current_command to a friendly name."""
    cmd = pane_cmd.strip()
    # Claude Code reports its version number as the command (e.g. "2.1.76")
    if _VERSION_RE.match(cmd):
        return "claude-code"
    cmd_lower = cmd.lower()
    shell_cmd = cmd_lower.lstrip("-")
    child_cmd = _process_command_line(pane_pid).lower()
    if shell_cmd in {"zsh", "bash", "fish", "sh"} and child_cmd and child_cmd != cmd_lower:
        for key, alias in PROCESS_ALIASES.items():
            if key in child_cmd:
                return alias
        for key, alias in NODE_DISAMBIGUATION.items():
            if key in child_cmd:
                return alias
    # "node" is ambiguous — both Claude Code and Codex run as node.
    # For tp ls (fast path): use session name / @task hints.
    # For tp status (slow path): inspect child process command line.
    if cmd_lower == "node":
        for key, alias in PROCESS_ALIASES.items():
            if key in child_cmd:
                return alias
        for key, alias in NODE_DISAMBIGUATION.items():
            if key in child_cmd:
                return alias
        name_lower = session_name.lower()
        for key, alias in NODE_DISAMBIGUATION.items():
            if key in name_lower:
                return alias
        # Version strings like "2.1.78" are Claude Code
        # Otherwise report as "node" (ambiguous)
        return "node"
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
    pid: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    agent_state: str = ""

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
            "agent_state": self.agent_state,
        }


_META_FMT = "\t".join(f"#{{@{k}}}" for k in METADATA_KEYS)
_SESSION_FMT = f"#{{session_name}}\t#{{pane_current_command}}\t#{{pane_current_path}}\t#{{pane_pid}}\t{_META_FMT}"


def _parse_session_line(line: str) -> SessionInfo | None:
    """Parse a single tab-separated tmux format line into a SessionInfo."""
    parts = line.split("\t")
    if len(parts) < 4:
        return None

    name, pane_cmd, pane_path, pane_pid = parts[0], parts[1], parts[2], parts[3]
    meta = {}
    for i, key in enumerate(METADATA_KEYS):
        val = parts[4 + i] if (4 + i) < len(parts) else ""
        if val:
            meta[key] = val

    return SessionInfo(
        name=name,
        process=_detect_process(pane_cmd, name, pane_pid),
        working_dir=pane_path,
        pid=pane_pid,
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

        if not info.metadata.get("branch") and info.working_dir:
            branch = _detect_git_branch(info.working_dir)
            if branch:
                info.metadata["branch"] = branch

        # Agent state detection is expensive (captures pane output).
        # Skip in list_sessions; compute on demand in get_session_status.
        info.agent_state = ""

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


def _set_metadata_option(session_name: str, key: str, value: str) -> None:
    """Set a single tmux @option value without touching companion timestamps."""
    _tmux("set-option", "-t", session_name, f"@{key}", value)


def set_metadata(session_name: str, key: str, value: str) -> None:
    """Set a @metadata value on a session and record when it changed."""
    _set_metadata_option(session_name, key, value)
    if key.endswith("_updated_at"):
        return
    _set_metadata_option(session_name, f"{key}_updated_at", _metadata_timestamp())


def _metadata_timestamp() -> str:
    """Return a UTC timestamp suitable for sortable tmux metadata."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _get_metadata_updated_at(session_name: str, keys: list[str]) -> dict[str, str]:
    """Fetch companion @<key>_updated_at timestamps for the given metadata keys."""
    timestamps: dict[str, str] = {}
    for key in keys:
        value = get_metadata(session_name, f"{key}_updated_at")
        if value:
            timestamps[key] = value
    return timestamps


def new_session(
    name: str,
    *,
    directory: str | None = None,
    desc: str | None = None,
    command: str | None = None,
) -> None:
    """Create a new detached tmux session with optional metadata."""
    cmd = ["tmux", "new-session", "-d", "-s", name]
    if directory:
        p = Path(directory).expanduser().resolve()
        cmd.extend(["-c", str(p)])
    if command:
        cmd.append(command)
    _run(cmd, check=True)

    if desc:
        set_metadata(name, "desc", desc)
    if directory:
        set_metadata(name, "repo", str(Path(directory).expanduser().resolve()))


def peek_session(name: str, lines: int = 50, timeout: int = 3) -> str:
    """Capture last N lines of scrollback from a session without attaching."""
    return _tmux("capture-pane", "-t", name, "-p", "-S", f"-{lines}", check=True, timeout=timeout)


def _normalize_directory(path: str) -> str:
    """Resolve a working directory path for stable comparisons."""
    if not path:
        return ""
    try:
        return str(Path(path).expanduser().resolve())
    except OSError:
        return str(Path(path).expanduser())


def _pane_current_path(session_name: str) -> str:
    """Return the tmux pane's current working directory."""
    return _tmux("display-message", "-t", session_name, "-p", "#{pane_current_path}", check=False)


def _wait_for_pane_path(
    session_name: str,
    expected_cwd: str,
    *,
    timeout: float = _CWD_VERIFY_TIMEOUT,
    interval: float = _CWD_VERIFY_INTERVAL,
) -> str:
    """Poll until the pane cwd matches *expected_cwd*, returning the last observed path."""
    expected = _normalize_directory(expected_cwd)
    deadline = time.monotonic() + timeout
    current = _pane_current_path(session_name)
    while _normalize_directory(current) != expected and time.monotonic() < deadline:
        time.sleep(interval)
        current = _pane_current_path(session_name)
    return current


def _ensure_session_cwd(session_name: str, expected_cwd: str) -> str:
    """Repair a drifted shell cwd before launching an agent."""
    expected = _normalize_directory(expected_cwd)
    current = _pane_current_path(session_name)
    if _normalize_directory(current) == expected:
        return expected

    send_keys(session_name, f"cd {shlex.quote(expected)}")
    current = _wait_for_pane_path(session_name, expected)
    if _normalize_directory(current) != expected:
        current_display = current or "<unknown>"
        raise RuntimeError(
            f"Session '{session_name}' pane cwd is '{current_display}', expected '{expected}'. "
            "tmux-pilot will not launch the agent until the pane is in the requested directory."
        )
    return expected


def _verify_session_cwd_after_launch(session_name: str, expected_cwd: str) -> str:
    """Fail loudly if the launched agent leaves the requested cwd immediately."""
    expected = _normalize_directory(expected_cwd)
    current = _wait_for_pane_path(session_name, expected)
    if _normalize_directory(current) != expected:
        current_display = current or "<unknown>"
        raise RuntimeError(
            f"Session '{session_name}' pane cwd changed to '{current_display}' after launching the agent; "
            f"expected '{expected}'."
        )
    return expected


def send_keys(name: str, text: str) -> None:
    """Send literal text, then press Enter in a separate tmux call.

    Interactive TUIs such as Codex can leave the prompt unsubmitted when text
    and Enter are bundled into a single `tmux send-keys` invocation.
    """
    if text:
        _tmux("send-keys", "-t", name, "-l", text)
        time.sleep(_SEND_KEYS_SETTLE_DELAY)
    _tmux("send-keys", "-t", name, "Enter")


def send_text(
    name: str,
    text: str,
    *,
    wait: bool = False,
    timeout: float = 30.0,
    interval: float = 0.25,
) -> dict[str, str | bool]:
    """Optionally wait for a session to become ready, then send text."""
    agent: dict[str, str | bool] = {}
    if wait:
        agent = wait_until_session_ready(name, timeout=timeout, interval=interval)
    send_keys(name, text)
    set_metadata(name, "last_send", _metadata_timestamp())
    return agent


def kill_session(name: str) -> None:
    """Kill a tmux session."""
    _tmux("kill-session", "-t", name)


def session_exists(name: str) -> bool:
    """Check if a session with the given name exists."""
    result = _run(["tmux", "has-session", "-t", name], check=False)
    return result.returncode == 0


def _exec_tmux_attach(target: str) -> None:
    """Replace the current process with `tmux attach-session`."""
    os.execvp("tmux", ["tmux", "attach-session", "-t", target])


def _attach_or_switch(target: str) -> None:
    """Attach or switch to a session by exact name."""
    if _is_inside_tmux():
        _tmux("switch-client", "-t", target)
    else:
        try:
            _exec_tmux_attach(target)
        except OSError as exc:
            raise RuntimeError(f"Failed to attach to session '{target}'") from exc


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
    return "TMUX" in os.environ


def _load_profile_tables(config_path: Path) -> dict[str, dict[str, object]]:
    if not config_path.exists():
        return {}

    with config_path.open("rb") as handle:
        data = tomllib.load(handle)

    if not isinstance(data, dict):
        return {}

    if isinstance(data.get("profiles"), dict):
        source = data["profiles"]
        tables = {name: values for name, values in source.items() if isinstance(values, dict)}
        default_values = data.get("default")
        if isinstance(default_values, dict) and "default" not in tables:
            tables["default"] = default_values
        return tables

    return {name: values for name, values in data.items() if isinstance(values, dict)}


def _resolve_profile_values(
    name: str,
    raw_profiles: dict[str, dict[str, object]],
    *,
    stack: tuple[str, ...] = (),
) -> dict[str, object]:
    if name in stack:
        cycle = " -> ".join((*stack, name))
        raise RuntimeError(f"Cyclic profile inheritance detected: {cycle}")
    if name not in raw_profiles:
        raise RuntimeError(f"Profile '{name}' not found in {PROFILE_CONFIG_PATH}")

    values = dict(raw_profiles[name])
    extends = values.get("extends")
    if isinstance(extends, str) and extends:
        base = _resolve_profile_values(extends, raw_profiles, stack=(*stack, name))
        merged = dict(base)
        merged.update(values)
        values = merged
    return values


def _normalize_profile_command(values: dict[str, object]) -> tuple[str, ...]:
    command = values.get("command")
    if isinstance(command, str):
        return tuple(shlex.split(command))
    if isinstance(command, list):
        return tuple(str(item) for item in command if str(item).strip())
    if isinstance(command, tuple):
        return tuple(str(item) for item in command if str(item).strip())

    agent = str(values.get("agent", "")).strip()
    agent_args = str(values.get("agent_args", "")).strip()
    if not agent:
        return ()
    return tuple(part for part in (agent, *shlex.split(agent_args)) if part)


def _normalize_profile_env(values: dict[str, object]) -> dict[str, str]:
    env = values.get("env")
    if not isinstance(env, dict):
        return {}
    return {str(key): str(value) for key, value in env.items()}


def _command_to_agent_fields(command: tuple[str, ...]) -> tuple[str, str]:
    if not command:
        return "", ""
    return command[0], " ".join(command[1:])


def load_profiles(path: Path | None = None) -> dict[str, SessionProfile]:
    """Load configured session profiles from TOML."""
    config_path = path or PROFILE_CONFIG_PATH
    raw_profiles = {name: dict(values) for name, values in _BUILTIN_PROFILE_DEFS.items()}
    for name, values in _load_profile_tables(config_path).items():
        if name in raw_profiles:
            merged = dict(raw_profiles[name])
            merged.update(values)
            raw_profiles[name] = merged
        else:
            raw_profiles[name] = dict(values)

    profiles: dict[str, SessionProfile] = {}
    for name in raw_profiles:
        values = _resolve_profile_values(name, raw_profiles)
        command = _normalize_profile_command(values)
        agent, agent_args = _command_to_agent_fields(command)
        profiles[name] = SessionProfile(
            name=name,
            extends=str(values.get("extends", "")),
            repo=str(values.get("repo", "")),
            agent=agent,
            agent_args=agent_args,
            command=command,
            env=_normalize_profile_env(values),
            clone_base=str(values.get("clone_base", _DEFAULT_CLONE_BASE)),
            worktree_base=str(values.get("worktree_base", _DEFAULT_WORKTREE_BASE)),
            branch_prefix=str(values.get("branch_prefix", "")),
            base_ref=str(values.get("base_ref", "")),
            prompt_wait_timeout=float(values.get("prompt_wait_timeout", 10.0)),
        )
    return profiles


def should_use_profile_mode(
    *,
    profile_name: str | None = None,
    issue: int | None = None,
    agent: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
    base_ref: str | None = None,
    no_agent: bool = False,
    prompt: str | None = None,
    directory: str | None = None,
    path: Path | None = None,
) -> bool:
    """Return True when `tp new` should use profile-backed creation."""
    profiles = load_profiles(path)

    if profile_name or issue is not None or repo or branch or base_ref or no_agent:
        return True
    if agent:
        return False
    if prompt:
        return "default" in profiles and not directory
    if directory:
        return False
    return "default" in profiles


def resolve_session_profile(
    profile_name: str | None = None,
    *,
    issue: int | None = None,
    repo_override: str | None = None,
    agent_override: str | None = None,
    path: Path | None = None,
) -> SessionProfile | None:
    """Resolve a profile, merging explicit settings with `[default]`."""
    profiles = load_profiles(path)
    if not profile_name and "default" not in profiles and not repo_override and not agent_override:
        return None

    if profile_name and profile_name not in profiles:
        raise RuntimeError(f"Profile '{profile_name}' not found in {path or PROFILE_CONFIG_PATH}")

    selected_name = profile_name or ("default" if "default" in profiles else "")
    default = profiles.get("default", SessionProfile(name="default"))
    selected = profiles.get(selected_name, SessionProfile(name=selected_name or "default"))
    command = selected.command_parts or default.command_parts

    branch_prefix = selected.branch_prefix or default.branch_prefix
    if not branch_prefix:
        branch_prefix = "fix" if issue is not None else "feat"

    agent = selected.agent or default.agent
    agent_args = selected.agent_args or default.agent_args
    if agent_override:
        override_command = tuple(shlex.split(agent_override))
        if not override_command:
            raise RuntimeError("Agent override produced an empty command")
        command = override_command
        agent, agent_args = _command_to_agent_fields(command)

    return SessionProfile(
        name=selected_name or "default",
        extends=selected.extends or default.extends,
        repo=repo_override or selected.repo or default.repo,
        agent=agent,
        agent_args=agent_args,
        command=command,
        env=dict(default.env) | dict(selected.env),
        clone_base=selected.clone_base or default.clone_base or _DEFAULT_CLONE_BASE,
        worktree_base=selected.worktree_base or default.worktree_base or _DEFAULT_WORKTREE_BASE,
        branch_prefix=branch_prefix,
        base_ref=selected.base_ref or default.base_ref,
        prompt_wait_timeout=selected.prompt_wait_timeout or default.prompt_wait_timeout or 10.0,
    )


def _slugify_branch_component(value: str) -> str:
    """Normalize a session name so it is safe to embed in a git branch name."""
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-").lower()


def _detect_git_branch(path: str) -> str:
    """Detect the current git branch for a working directory."""
    if not path:
        return ""
    result = _run(
        ["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"],
        check=False,
        timeout=3,
    )
    if result.returncode != 0:
        return ""
    branch = result.stdout.strip()
    return "" if branch == "HEAD" else branch


def _git(args: list[str], *, cwd: str, check: bool = True, timeout: int = 15) -> str:
    """Run a git command inside a repository."""
    result = _run(["git", *args], check=check, cwd=cwd, timeout=timeout)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def _fetch_issue_title(repo_path: str, issue_number: int) -> str:
    """Fetch a GitHub issue title for metadata."""
    result = _run(
        ["gh", "issue", "view", str(issue_number), "--json", "title", "-q", ".title"],
        check=False,
        cwd=repo_path,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Failed to fetch issue #{issue_number}")
    return result.stdout.strip()


def launch_agent_session(
    session_name: str,
    command: str,
    *,
    prompt: str | None = None,
    expected_cwd: str | None = None,
    prompt_timeout: float = 30.0,
) -> None:
    """Launch a shell command in a tmux session and optionally send a prompt."""
    if expected_cwd:
        _ensure_session_cwd(session_name, expected_cwd)
    send_keys(session_name, command)
    if expected_cwd:
        _verify_session_cwd_after_launch(session_name, expected_cwd)
    if prompt:
        send_text(session_name, prompt, wait=True, timeout=prompt_timeout)


def _git_root(path: str) -> str:
    """Return the git root for *path*, or an empty string when not in a repo."""
    if not path:
        return ""
    result = _run(
        ["git", "-C", path, "rev-parse", "--show-toplevel"],
        check=False,
        timeout=3,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def inspect_directory_context(directory: str) -> dict[str, str]:
    """Inspect a directory and derive git-aware session metadata."""
    resolved_dir = _normalize_directory(directory)
    repo_root = _git_root(resolved_dir)
    branch = _detect_git_branch(resolved_dir) if repo_root else ""
    origin = ""
    if repo_root:
        origin = "git-worktree" if _is_git_worktree(repo_root) else "git-repo"

    return {
        "directory": resolved_dir,
        "repo": repo_root or resolved_dir,
        "branch": branch,
        "origin": origin,
    }


def infer_session_name_for_directory(directory: str) -> str:
    """Infer a tmux session name from a directory or its repo/worktree root."""
    context = inspect_directory_context(directory)
    raw_name = Path(context["repo"]).name or Path(context["directory"]).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_name).strip("-")
    if not name:
        raise RuntimeError(
            f"Could not infer a session name from '{context['directory']}'. "
            "Pass an explicit session name."
        )
    return name


def uniqueify_session_name(base_name: str) -> str:
    """Return *base_name* or the next available -N suffixed variant."""
    if not session_exists(base_name):
        return base_name

    suffix = 1
    while True:
        candidate = f"{base_name}-{suffix}"
        if not session_exists(candidate):
            return candidate
        suffix += 1


def apply_directory_metadata(session_name: str, directory: str) -> dict[str, str]:
    """Set repo/branch/origin metadata for a session from a local directory."""
    context = inspect_directory_context(directory)

    set_metadata(session_name, "repo", context["repo"])
    if context["branch"]:
        set_metadata(session_name, "branch", context["branch"])
    if context["origin"]:
        set_metadata(session_name, "origin", context["origin"])

    return context


def _parse_github_repo(repo: str) -> tuple[str, str] | None:
    match = _GITHUB_REPO_RE.match(repo.strip())
    if not match:
        return None
    return match.group("owner"), match.group("repo")


def _clone_github_repo(repo: str, *, clone_base: str) -> str:
    parsed = _parse_github_repo(repo)
    if parsed is None:
        raise RuntimeError(f"Unsupported repository source '{repo}'")

    owner, repo_name = parsed
    clone_root = Path(clone_base).expanduser().resolve()
    local_path = clone_root / repo_name
    if local_path.exists():
        return str(local_path.resolve())

    clone_root.mkdir(parents=True, exist_ok=True)
    result = _run(
        ["git", "clone", f"https://github.com/{owner}/{repo_name}.git", str(local_path)],
        check=False,
        cwd=str(clone_root),
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Failed to clone {repo}")
    return str(local_path.resolve())


def _resolve_repo_source(repo: str, *, clone_base: str) -> str:
    candidate = Path(repo).expanduser()
    if candidate.exists():
        return str(candidate.resolve())

    parsed = _parse_github_repo(repo)
    if parsed is None:
        raise RuntimeError(f"Repository '{repo}' was not found locally and is not a GitHub repo slug/URL")
    return _clone_github_repo(repo, clone_base=clone_base)


def _detect_base_ref(repo_path: str, configured_base_ref: str = "") -> str:
    if configured_base_ref:
        return configured_base_ref

    remote_head = _git(
        ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
        cwd=repo_path,
        check=False,
    )
    if remote_head:
        return remote_head

    current_branch = _detect_git_branch(repo_path)
    if current_branch:
        return current_branch
    return "HEAD"


def _local_branch_exists(repo_path: str, branch: str) -> bool:
    result = _run(
        ["git", "-C", repo_path, "show-ref", "--verify", f"refs/heads/{branch}"],
        check=False,
        timeout=5,
    )
    return result.returncode == 0


def _fetch_base_ref(repo_path: str, base_ref: str) -> None:
    if "/" not in base_ref:
        return
    remote = base_ref.split("/", 1)[0]
    result = _run(["git", "-C", repo_path, "remote", "get-url", remote], check=False, timeout=5)
    if result.returncode != 0:
        return
    _git(["fetch", remote], cwd=repo_path, check=False, timeout=30)


def _prepare_worktree(repo_path: str, *, worktree_dir: Path, branch: str, base_ref: str) -> None:
    if worktree_dir.exists():
        raise RuntimeError(f"Worktree path already exists: {worktree_dir}")

    if _local_branch_exists(repo_path, branch):
        _git(["worktree", "add", str(worktree_dir), branch], cwd=repo_path)
        return

    _fetch_base_ref(repo_path, base_ref)
    _git(["worktree", "add", "-b", branch, str(worktree_dir), base_ref], cwd=repo_path)


class _TemplateDict(dict[str, str]):
    def __missing__(self, key: str) -> str:  # pragma: no cover - defensive
        raise RuntimeError(f"Unknown profile template key '{key}'")


def _render_profile_value(value: str, context: dict[str, str]) -> str:
    try:
        return value.format_map(_TemplateDict(context))
    except ValueError as exc:
        raise RuntimeError(f"Invalid profile template '{value}': {exc}") from exc


def _profile_context(
    *,
    profile: SessionProfile,
    name: str,
    working_dir: str,
    repo_path: str = "",
    branch: str = "",
    issue: int | None = None,
    issue_title: str = "",
    base_ref: str = "",
) -> dict[str, str]:
    profile_root = Path(working_dir) / ".tmux-pilot" / profile.name
    session_dir = str(profile_root / "sessions")
    context = {
        "name": name,
        "session_name": name,
        "task_slug": _slugify_branch_component(name),
        "worktree": working_dir,
        "repo_path": repo_path,
        "repo_name": Path(repo_path).name if repo_path else Path(working_dir).name,
        "branch": branch,
        "issue": str(issue) if issue is not None else "",
        "issue_title": issue_title,
        "base_ref": base_ref,
        "profile": profile.name,
        "profile_root": str(profile_root),
        "session_dir": session_dir,
    }
    return context


def _render_launch_command(profile: SessionProfile, context: dict[str, str]) -> str:
    """Render the configured agent command for direct tmux startup."""
    command_parts = [
        _render_profile_value(part, context)
        for part in profile.command_parts
    ]
    if not command_parts:
        return ""

    for key in ("profile_root", "session_dir"):
        value = context.get(key, "")
        if value:
            Path(value).mkdir(parents=True, exist_ok=True)

    env_parts = [
        f"{key}={shlex.quote(_render_profile_value(value, context))}"
        for key, value in profile.env.items()
    ]
    return " ".join(env_parts + [shlex.quote(part) for part in command_parts])


def _initial_prompt_desc(desc: str | None, issue_title: str) -> str | None:
    return issue_title or desc


def _bootstrap_worktree_leaf_name(repo_name: str, session_name: str) -> str:
    """Build a stable worktree leaf name without repeating the repo prefix."""
    repo_name_folded = repo_name.casefold()
    session_name_folded = session_name.casefold()
    repo_prefix = f"{repo_name_folded}-"
    if session_name_folded == repo_name_folded or session_name_folded.startswith(repo_prefix):
        return session_name
    return f"{repo_name}-{session_name}"


def _create_bootstrap_workspace(
    *,
    profile: SessionProfile,
    name: str,
    repo_source: str,
    issue: int | None = None,
    branch: str | None = None,
    base_ref: str | None = None,
) -> dict[str, str]:
    repo_path = _resolve_repo_source(repo_source, clone_base=profile.clone_base)
    worktree_base = Path(profile.worktree_base).expanduser().resolve()
    worktree_dir = worktree_base / _bootstrap_worktree_leaf_name(Path(repo_path).name, name)

    branch_name = branch or f"{profile.branch_prefix}/{_slugify_branch_component(name)}"
    if issue is not None and branch is None:
        branch_name = f"{profile.branch_prefix}/{issue}-{_slugify_branch_component(name)}"

    resolved_base_ref = _detect_base_ref(repo_path, base_ref or profile.base_ref)
    _prepare_worktree(repo_path, worktree_dir=worktree_dir, branch=branch_name, base_ref=resolved_base_ref)

    return {
        "repo": repo_path,
        "worktree": str(worktree_dir),
        "branch": branch_name,
        "base_ref": resolved_base_ref,
    }


def create_profile_session(
    name: str,
    *,
    profile_name: str | None = None,
    issue: int | None = None,
    agent: str | None = None,
    repo: str | None = None,
    directory: str | None = None,
    branch: str | None = None,
    base_ref: str | None = None,
    no_agent: bool = False,
    prompt: str | None = None,
    desc: str | None = None,
    config_path: Path | None = None,
) -> dict[str, str]:
    """Create a configured tmux session, optionally bootstrapped from a repo task."""
    profile = resolve_session_profile(
        profile_name,
        issue=issue,
        repo_override=repo,
        agent_override=agent,
        path=config_path,
    )
    if profile is None:
        raise RuntimeError("No profile, agent, or repo bootstrap configuration was resolved")

    repo_source = profile.repo
    if not repo_source and (issue is not None or branch or base_ref):
        repo_source = _git_root(directory or os.getcwd())
    if issue is not None and not repo_source:
        raise RuntimeError("Issue-based sessions require a git repo; pass --repo or run tp from a git checkout")
    if (branch or base_ref) and not repo_source:
        raise RuntimeError("Branch/base-ref options require a git repo; pass --repo or run tp from a git checkout")

    workspace: dict[str, str] = {}
    working_dir = ""
    if repo_source:
        workspace = _create_bootstrap_workspace(
            profile=profile,
            name=name,
            repo_source=repo_source,
            issue=issue,
            branch=branch,
            base_ref=base_ref,
        )
        working_dir = workspace["worktree"]
    else:
        working_dir = str(Path(directory or os.getcwd()).expanduser().resolve())

    issue_title = ""
    if issue is not None:
        issue_repo = workspace.get("repo", _git_root(working_dir))
        if issue_repo:
            issue_title = _fetch_issue_title(issue_repo, issue)

    session_desc = _initial_prompt_desc(desc, issue_title)
    rendered_command = ""
    if not no_agent and profile.command_parts:
        context = _profile_context(
            profile=profile,
            name=name,
            working_dir=working_dir,
            repo_path=workspace.get("repo", _git_root(working_dir)),
            branch=workspace.get("branch", _detect_git_branch(working_dir)),
            issue=issue,
            issue_title=issue_title,
            base_ref=workspace.get("base_ref", base_ref or ""),
        )
        rendered_command = _render_launch_command(profile, context)

    new_session(name, directory=working_dir, desc=session_desc)

    repo_path = workspace.get("repo", _git_root(working_dir))
    branch_name = workspace.get("branch", _detect_git_branch(working_dir))
    set_metadata(name, "task", name)
    if repo_path:
        set_metadata(name, "repo", repo_path)
    if branch_name:
        set_metadata(name, "branch", branch_name)
    if repo_path or profile.command_parts or no_agent:
        set_metadata(name, "status", "active")
    if issue_title:
        set_metadata(name, "desc", issue_title)

    if rendered_command:
        launch_agent_session(
            name,
            rendered_command,
            prompt=prompt,
            expected_cwd=working_dir,
            prompt_timeout=profile.prompt_wait_timeout,
        )

    return {
        "repo": repo_path,
        "worktree": working_dir,
        "branch": branch_name,
        "agent": rendered_command or " ".join(profile.command_parts),
        "desc": issue_title or desc or "",
    }


def _get_agent_state(
    session_name: str,
    pane_command: str,
    pane_output: str | None = None,
    *,
    pane_path: str = "",
    transcript_path: Path | None = None,
) -> dict[str, str | bool]:
    """Detect the active agent plugin and return its current state."""
    from .plugins.agents import get_agent_state

    if not pane_path and session_exists(session_name):
        pane_path = _tmux("display-message", "-t", session_name, "-p", "#{pane_current_path}", check=False)
    return get_agent_state(
        session_name,
        pane_command,
        pane_output=pane_output,
        working_dir=pane_path,
        transcript_path=transcript_path,
    )


def _session_pane_details(name: str) -> tuple[str, str, str, dict[str, str]]:
    """Fetch pane command, path, pid, and metadata in one tmux call."""
    pane_fmt = "#{pane_current_command}\t#{pane_current_path}\t#{pane_pid}\t" + _META_FMT
    raw = _tmux("list-panes", "-t", name, "-F", pane_fmt)
    parts = raw.splitlines()[0].split("\t") if raw else []

    pane_cmd = parts[0] if len(parts) > 0 else ""
    pane_path = parts[1] if len(parts) > 1 else ""
    pane_pid = parts[2] if len(parts) > 2 else ""

    meta: dict[str, str] = {}
    for i, key in enumerate(METADATA_KEYS):
        val = parts[3 + i] if (3 + i) < len(parts) else ""
        if val:
            meta[key] = val

    if not meta.get("branch") and pane_path:
        branch = _detect_git_branch(pane_path)
        if branch:
            meta["branch"] = branch

    return pane_cmd, pane_path, pane_pid, meta


def _agent_is_ready(agent: dict[str, str | bool]) -> bool:
    ready = agent.get("ready")
    if isinstance(ready, bool):
        return ready
    state = agent.get("state")
    return isinstance(state, str) and state in {"idle", "completed"}


def wait_until_session_ready(
    name: str,
    *,
    timeout: float = 30.0,
    interval: float = 0.25,
) -> dict[str, str | bool]:
    """Wait until a session's active agent is ready for more input."""
    if not session_exists(name):
        raise RuntimeError(f"Session '{name}' not found")

    from . import agent_sessions

    pane_cmd, pane_path, pane_pid, _meta = _session_pane_details(name)
    detected_process = _detect_process(pane_cmd, name, pane_pid)
    transcript_path: Path | None = None
    deadline = time.monotonic() + timeout

    while True:
        pane_output = peek_session(name, lines=200)
        agent = _get_agent_state(
            name,
            detected_process,
            pane_output=pane_output,
            pane_path=pane_path,
            transcript_path=transcript_path,
        )

        agent_type = agent.get("type")
        if isinstance(agent_type, str) and pane_path and transcript_path is None:
            transcript_path = agent_sessions.find_transcript_for_cwd(agent_type, pane_path)
            if transcript_path is not None:
                agent = _get_agent_state(
                    name,
                    detected_process,
                    pane_output=pane_output,
                    pane_path=pane_path,
                    transcript_path=transcript_path,
                )

        if _agent_is_ready(agent):
            return agent
        if time.monotonic() >= deadline:
            state = agent.get("state", "unknown")
            raise RuntimeError(f"Timed out waiting for session '{name}' to become ready (last state: {state})")
        time.sleep(interval)


DONE_STATUSES = {"done", "complete", "completed", "finished", "merged"}


def _is_git_worktree(path: str) -> bool:
    """Check if a path is a git worktree (not the main working tree)."""
    if not path or not Path(path).is_dir():
        return False
    result = _run(
        ["git", "-C", path, "rev-parse", "--git-common-dir"],
        check=False, timeout=3,
    )
    if result.returncode != 0:
        return False
    common = result.stdout.strip()
    result2 = _run(
        ["git", "-C", path, "rev-parse", "--git-dir"],
        check=False, timeout=3,
    )
    if result2.returncode != 0:
        return False
    git_dir = result2.stdout.strip()
    # In a worktree, git-dir is something like ../.git/worktrees/name
    # while git-common-dir is ../.git — they differ.
    return Path(git_dir).resolve() != Path(common).resolve()


def _remove_worktree(path: str) -> bool:
    """Remove a git worktree. Returns True if removed."""
    result = _run(["git", "worktree", "remove", "--force", path], check=False, timeout=10)
    return result.returncode == 0


def _is_branch_merged(path: str, branch: str) -> bool:
    """Check if a branch is merged into the main branch."""
    result = _run(
        ["git", "-C", path, "branch", "--merged", "HEAD", "--list", branch],
        check=False, timeout=5,
    )
    return result.returncode == 0 and branch in (result.stdout or "")


def _delete_branch(path: str, branch: str) -> bool:
    """Delete a local git branch. Returns True if deleted."""
    result = _run(["git", "-C", path, "branch", "-d", branch], check=False, timeout=5)
    return result.returncode == 0


def clean_sessions(
    *,
    target: str | None = None,
    status_filter: str | None = None,
    dry_run: bool = False,
) -> list[dict]:
    """Clean up done-ish sessions, their worktrees, and merged branches.

    Returns a list of action dicts describing what was (or would be) done.
    """
    if target:
        sessions = list_sessions()
        matches = [s for s in sessions if s.name == target]
        if not matches:
            matches = [s for s in sessions if target.lower() in s.name.lower()]
        if not matches:
            raise RuntimeError(f"No session matching '{target}'")
    else:
        filter_statuses = {s.strip().lower() for s in (status_filter or "done").split(",")}
        if not status_filter:
            filter_statuses = DONE_STATUSES
        sessions = list_sessions()
        matches = [s for s in sessions if s.status.lower() in filter_statuses]

    actions: list[dict] = []
    for s in matches:
        action: dict = {"session": s.name, "killed": False, "worktree_removed": False, "branch_deleted": False}
        wdir = s.working_dir
        branch = s.metadata.get("branch", "")

        if dry_run:
            action["dry_run"] = True
            action["would_kill"] = True
            action["would_remove_worktree"] = bool(wdir) and _is_git_worktree(wdir)
            actions.append(action)
            continue

        # Kill the session
        kill_session(s.name)
        action["killed"] = True

        # Remove worktree if applicable
        if wdir and _is_git_worktree(wdir):
            action["worktree_removed"] = _remove_worktree(wdir)

        # Delete merged branch if applicable
        if branch and wdir:
            # Use parent of worktree or repo path for branch ops
            repo = s.metadata.get("repo", wdir)
            if _is_branch_merged(repo, branch):
                action["branch_deleted"] = _delete_branch(repo, branch)

        actions.append(action)
    return actions


def get_session_status(name: str) -> dict:
    """Get detailed status for a session using batched format strings."""
    if not session_exists(name):
        raise RuntimeError(f"Session '{name}' not found")

    pane_cmd, pane_path, pane_pid, meta = _session_pane_details(name)
    metadata_updated_at = _get_metadata_updated_at(name, list(meta))
    scrollback = peek_session(name, lines=5)
    agent = _get_agent_state(
        name,
        _detect_process(pane_cmd, name, pane_pid),
        pane_path=pane_path,
    )

    return {
        "name": name,
        "process": _detect_process(pane_cmd, name, pane_pid),
        "pid": pane_pid,
        "working_dir": pane_path,
        "metadata": meta,
        "metadata_updated_at": metadata_updated_at,
        "scrollback_tail": scrollback,
        "agent": agent,
    }
