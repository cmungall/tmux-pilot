"""Core tmux interaction: list, create, peek, send, kill, metadata."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib  # type: ignore[import-not-found]

# Metadata keys stored as tmux user options (@-prefixed)
METADATA_KEYS = ("repo", "task", "desc", "status", "origin", "branch", "needs", "last_commit", "pr", "pr_state", "pushing")

# Map pane_current_command to friendly process names
PROCESS_ALIASES: dict[str, str] = {
    "claude": "claude-code",
    "codex": "codex",
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
_DEFAULT_WORKTREE_BASE = "~/worktrees"


@dataclass
class SessionProfile:
    """Resolved project profile for `tp new --profile`."""

    name: str
    repo: str = ""
    agent: str = ""
    agent_args: str = ""
    worktree_base: str = _DEFAULT_WORKTREE_BASE
    branch_prefix: str = ""


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


def _detect_process(pane_cmd: str, session_name: str = "") -> str:
    """Map a pane_current_command to a friendly name."""
    cmd = pane_cmd.strip()
    # Claude Code reports its version number as the command (e.g. "2.1.76")
    if _VERSION_RE.match(cmd):
        return "claude-code"
    cmd_lower = cmd.lower()
    # "node" is ambiguous — both Claude Code and Codex run as node.
    # For tp ls (fast path): use session name / @task hints.
    # For tp status (slow path): inspect child process command line.
    if cmd_lower == "node":
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
        process=_detect_process(pane_cmd, name),
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
    return "TMUX" in os.environ


def load_profiles(path: Path | None = None) -> dict[str, SessionProfile]:
    """Load configured session profiles from TOML."""
    config_path = path or PROFILE_CONFIG_PATH
    if not config_path.exists():
        return {}

    with config_path.open("rb") as handle:
        data = tomllib.load(handle)

    profiles: dict[str, SessionProfile] = {}
    for name, values in data.items():
        if not isinstance(values, dict):
            continue
        profiles[name] = SessionProfile(
            name=name,
            repo=str(values.get("repo", "")),
            agent=str(values.get("agent", "")),
            agent_args=str(values.get("agent_args", "")),
            worktree_base=str(values.get("worktree_base", _DEFAULT_WORKTREE_BASE)),
            branch_prefix=str(values.get("branch_prefix", "")),
        )
    return profiles


def should_use_profile_mode(
    *,
    profile_name: str | None = None,
    issue: int | None = None,
    agent: str | None = None,
    repo: str | None = None,
    no_agent: bool = False,
    prompt: str | None = None,
    path: Path | None = None,
) -> bool:
    """Return True when `tp new` should use profile-backed creation."""
    if profile_name or issue is not None or agent or repo or no_agent or prompt:
        return True
    return "default" in load_profiles(path)


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
    if not profiles and not repo_override and not agent_override:
        return None

    if profile_name and profile_name not in profiles:
        raise RuntimeError(f"Profile '{profile_name}' not found in {path or PROFILE_CONFIG_PATH}")

    selected_name = profile_name or ("default" if "default" in profiles else "")
    default = profiles.get("default", SessionProfile(name="default"))
    selected = profiles.get(selected_name, SessionProfile(name=selected_name or "default"))

    branch_prefix = selected.branch_prefix or default.branch_prefix
    if not branch_prefix:
        branch_prefix = "fix" if issue is not None else "feat"

    return SessionProfile(
        name=selected_name or "default",
        repo=repo_override or selected.repo or default.repo,
        agent=agent_override or selected.agent or default.agent,
        agent_args=selected.agent_args or default.agent_args,
        worktree_base=selected.worktree_base or default.worktree_base or _DEFAULT_WORKTREE_BASE,
        branch_prefix=branch_prefix,
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


def _launch_agent(session_name: str, agent: str, agent_args: str = "") -> None:
    """Launch the configured agent inside the tmux session."""
    command = " ".join(part for part in (agent.strip(), agent_args.strip()) if part)
    if command:
        send_keys(session_name, command)


def create_profile_session(
    name: str,
    *,
    profile_name: str | None = None,
    issue: int | None = None,
    agent: str | None = None,
    repo: str | None = None,
    no_agent: bool = False,
    prompt: str | None = None,
    desc: str | None = None,
    config_path: Path | None = None,
) -> dict[str, str]:
    """Create a worktree-backed tmux session from a resolved profile."""
    profile = resolve_session_profile(
        profile_name,
        issue=issue,
        repo_override=repo,
        agent_override=agent,
        path=config_path,
    )
    if profile is None or not profile.repo:
        raise RuntimeError("No repo configured for profile-based session creation")

    repo_path = str(Path(profile.repo).expanduser().resolve())
    worktree_base = Path(profile.worktree_base).expanduser().resolve()
    worktree_dir = worktree_base / f"{Path(repo_path).name}-{name}"

    branch_slug = _slugify_branch_component(name)
    branch = f"{profile.branch_prefix}/{branch_slug}"
    if issue is not None:
        branch = f"{profile.branch_prefix}/{issue}-{branch_slug}"

    issue_title = _fetch_issue_title(repo_path, issue) if issue is not None else ""

    _git(["fetch", "origin"], cwd=repo_path)
    _git(
        ["worktree", "add", "-b", branch, str(worktree_dir), "origin/main"],
        cwd=repo_path,
    )

    new_session(name, directory=str(worktree_dir), desc=issue_title or desc)
    set_metadata(name, "repo", repo_path)
    set_metadata(name, "branch", branch)
    set_metadata(name, "status", "active")
    if issue_title:
        set_metadata(name, "desc", issue_title)

    if not no_agent and profile.agent:
        _launch_agent(name, profile.agent, profile.agent_args)
        if prompt:
            time.sleep(5)
            send_keys(name, prompt)

    return {
        "repo": repo_path,
        "worktree": str(worktree_dir),
        "branch": branch,
        "agent": profile.agent,
        "desc": issue_title or desc or "",
    }


def _get_agent_state(session_name: str, pane_command: str, pane_output: str | None = None) -> dict[str, str]:
    """Detect the active agent plugin and return its current state."""
    from .plugins.agents import get_agent_state

    return get_agent_state(session_name, pane_command, pane_output=pane_output)


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

    if not meta.get("branch") and pane_path:
        branch = _detect_git_branch(pane_path)
        if branch:
            meta["branch"] = branch

    scrollback = peek_session(name, lines=5)
    agent = _get_agent_state(name, _detect_process(pane_cmd, name))

    return {
        "name": name,
        "process": _detect_process(pane_cmd),
        "pid": pane_pid,
        "working_dir": pane_path,
        "metadata": meta,
        "scrollback_tail": scrollback,
        "agent": agent,
    }
