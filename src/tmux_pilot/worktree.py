"""Worktree scanning, summarisation, and cleanup."""

from __future__ import annotations

import json as _json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .core import (
    SessionInfo,
    _worktree_parent_repo,
    is_branch_merged,
    list_sessions,
    remove_worktree,
    delete_branch,
)

_DEFAULT_WORKTREE_BASE = "~/worktrees"


def _run_git(args: list[str], *, cwd: str | None = None, timeout: int = 10) -> subprocess.CompletedProcess:
    """Run a git command, returning CompletedProcess. Never raises on failure."""
    try:
        return subprocess.run(
            args, capture_output=True, text=True, check=False, cwd=cwd, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="timeout")


@dataclass
class WorktreeInfo:
    """Information about a single git worktree directory."""

    path: str
    repo_name: str
    branch: str
    last_commit_date: datetime | None
    age_days: float
    has_session: bool
    session_name: str | None
    agent_type: str  # "claude" | "codex" | "unknown"
    is_merged: bool
    has_unpushed: bool
    has_uncommitted: bool

    @property
    def is_orphan(self) -> bool:
        """True if no tmux session is using this worktree."""
        return not self.has_session

    @property
    def is_stale(self) -> bool:
        """True if last commit is older than 7 days."""
        return self.age_days > 7

    def to_dict(self) -> dict:
        """Serialize to a plain dict."""
        return {
            "path": self.path,
            "repo_name": self.repo_name,
            "branch": self.branch,
            "last_commit_date": self.last_commit_date.isoformat() if self.last_commit_date else None,
            "age_days": round(self.age_days, 1),
            "has_session": self.has_session,
            "session_name": self.session_name,
            "agent_type": self.agent_type,
            "is_merged": self.is_merged,
            "has_unpushed": self.has_unpushed,
            "has_uncommitted": self.has_uncommitted,
            "is_orphan": self.is_orphan,
            "is_stale": self.is_stale,
        }


def _detect_agent_type(wt_path: str, branch: str = "") -> str:
    """Detect agent type from branch name and directory markers.

    Branch prefix is the strongest signal. Directory markers like .claude/
    are often checked into repos and inherited by all worktrees, so they
    are only used as a tiebreaker when .codex/ is absent.
    """
    # Branch prefix is authoritative
    if branch.startswith("codex/"):
        return "codex"
    if branch.startswith("claude/"):
        return "claude"
    # .codex/ without a claude branch prefix → codex
    # (.claude/ is too common to be useful — most repos check it in)
    has_codex = os.path.isdir(os.path.join(wt_path, ".codex"))
    if has_codex:
        return "codex"
    return "unknown"


def _read_repo_name(wt_path: str) -> str:
    """Extract repo name from .git file gitdir pointer."""
    git_path = os.path.join(wt_path, ".git")
    if os.path.isfile(git_path):
        content = Path(git_path).read_text().strip()
        # Format: "gitdir: /path/to/repo/.git/worktrees/branch-name"
        if content.startswith("gitdir:"):
            gitdir = content[len("gitdir:"):].strip()
            # Walk up from .git/worktrees/X to get the repo root
            parts = Path(gitdir).parts
            if ".git" in parts:
                git_idx = len(parts) - 1 - list(reversed(parts)).index(".git")
                repo_root = Path(*parts[:git_idx]) if git_idx > 0 else Path("/")
                return repo_root.name
    return os.path.basename(wt_path)


def _probe_worktree(wt_path: str, *, full: bool = False) -> dict:
    """Gather git info for a single worktree directory."""
    result: dict = {"path": wt_path}

    # Single git call for branch + last commit date
    r = _run_git(
        ["git", "log", "-1", "--format=%D%n%aI"],
        cwd=wt_path, timeout=5,
    )
    if r.returncode == 0 and r.stdout.strip():
        lines = r.stdout.strip().splitlines()
        # First line: refs (e.g. "HEAD -> feat/foo, origin/feat/foo")
        refs_line = lines[0] if lines else ""
        branch = ""
        for ref in refs_line.split(","):
            ref = ref.strip()
            if ref.startswith("HEAD -> "):
                branch = ref[len("HEAD -> "):]
                break
        result["branch"] = branch
        # Second line: author date ISO
        date_str = lines[1].strip() if len(lines) > 1 else ""
        if date_str:
            try:
                result["last_commit_date"] = datetime.fromisoformat(date_str)
            except ValueError:
                result["last_commit_date"] = None
        else:
            result["last_commit_date"] = None
    else:
        result["branch"] = ""
        result["last_commit_date"] = None

    # Uncommitted changes — only in full mode (expensive for 554 worktrees)
    if full:
        r = _run_git(["git", "status", "--porcelain"], cwd=wt_path, timeout=5)
        result["has_uncommitted"] = r.returncode == 0 and bool(r.stdout.strip())
    else:
        result["has_uncommitted"] = False

    # Full mode: merged and unpushed checks
    if full:
        branch = result["branch"]
        if branch:
            r = _run_git(
                ["git", "branch", "--merged", "HEAD", "--list", branch],
                cwd=wt_path, timeout=5,
            )
            result["is_merged"] = r.returncode == 0 and branch in (r.stdout or "")

            r = _run_git(["git", "log", "@{u}..HEAD", "--oneline"], cwd=wt_path, timeout=5)
            result["has_unpushed"] = r.returncode == 0 and bool(r.stdout.strip())
        else:
            result["is_merged"] = False
            result["has_unpushed"] = False
    else:
        result["is_merged"] = False
        result["has_unpushed"] = False

    return result


def scan_worktrees(
    base: str = _DEFAULT_WORKTREE_BASE,
    *,
    repo: str | None = None,
    stale_days: int | None = None,
    orphan_only: bool = False,
    full: bool = False,
) -> list[WorktreeInfo]:
    """Scan worktree directories and return structured info.

    Args:
        base: Base directory containing worktrees (default ~/worktrees).
        repo: Filter to worktrees belonging to this repo name.
        stale_days: If set, only return worktrees older than this many days.
        orphan_only: If True, only return worktrees with no tmux session.
        full: If True, also check merged/unpushed status (slower).
    """
    base_expanded = os.path.expanduser(base)
    if not os.path.isdir(base_expanded):
        return []

    # Phase 1: Scan directories
    candidates: list[tuple[str, str]] = []  # (path, repo_name)
    with os.scandir(base_expanded) as entries:
        for entry in entries:
            if not entry.is_dir(follow_symlinks=False):
                continue
            wt_path = entry.path
            # Must have a .git file (worktree indicator)
            git_file = os.path.join(wt_path, ".git")
            if not os.path.exists(git_file):
                continue
            repo_name = _read_repo_name(wt_path)
            if repo and repo_name != repo:
                continue
            candidates.append((wt_path, repo_name))

    if not candidates:
        return []

    # Phase 2: Parallel git queries
    def _probe(item: tuple[str, str]) -> dict:
        wt_path, repo_name = item
        info = _probe_worktree(wt_path, full=full)
        info["repo_name"] = repo_name
        # Detect agent using both directory and branch info
        info["agent_type"] = _detect_agent_type(wt_path, info.get("branch", ""))
        return info

    with ThreadPoolExecutor(max_workers=16) as pool:
        probed = list(pool.map(_probe, candidates))

    # Phase 3: Cross-reference with tmux sessions
    sessions = list_sessions()
    session_by_dir: dict[str, SessionInfo] = {}
    for s in sessions:
        if s.working_dir:
            session_by_dir[s.working_dir] = s

    now = datetime.now(timezone.utc)
    results: list[WorktreeInfo] = []

    for info in probed:
        wt_path = info["path"]
        session = session_by_dir.get(wt_path)

        last_commit_date = info["last_commit_date"]
        if last_commit_date:
            if last_commit_date.tzinfo is None:
                last_commit_date = last_commit_date.replace(tzinfo=timezone.utc)
            age_days = (now - last_commit_date).total_seconds() / 86400
        else:
            age_days = 999.0  # Unknown age treated as very old

        wt = WorktreeInfo(
            path=wt_path,
            repo_name=info["repo_name"],
            branch=info["branch"],
            last_commit_date=last_commit_date,
            age_days=age_days,
            has_session=session is not None,
            session_name=session.name if session else None,
            agent_type=info["agent_type"],
            is_merged=info["is_merged"],
            has_unpushed=info["has_unpushed"],
            has_uncommitted=info["has_uncommitted"],
        )

        # Apply filters
        if orphan_only and not wt.is_orphan:
            continue
        if stale_days is not None and wt.age_days <= stale_days:
            continue

        results.append(wt)

    return results


def worktree_summary(worktrees: list[WorktreeInfo]) -> dict:
    """Return counts by repo and by status category."""
    by_repo: dict[str, int] = {}
    categories = {"orphan": 0, "stale": 0, "active": 0, "merged": 0}

    for wt in worktrees:
        by_repo[wt.repo_name] = by_repo.get(wt.repo_name, 0) + 1
        if wt.is_merged:
            categories["merged"] += 1
        elif wt.is_orphan:
            categories["orphan"] += 1
        elif wt.is_stale:
            categories["stale"] += 1
        else:
            categories["active"] += 1

    return {
        "total": len(worktrees),
        "by_repo": by_repo,
        "by_status": categories,
    }


_PR_CACHE_PATH = Path.home() / ".cache" / "tmux-pilot" / "wt-pr-cache.json"


def _load_pr_cache() -> dict[str, dict]:
    """Load PR cache from disk."""
    if _PR_CACHE_PATH.is_file():
        return _json.loads(_PR_CACHE_PATH.read_text())
    return {}


def _save_pr_cache(cache: dict[str, dict]) -> None:
    """Save PR cache to disk."""
    _PR_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PR_CACHE_PATH.write_text(_json.dumps(cache, indent=2))


def get_cached_pr(wt_path: str) -> dict | None:
    """Get cached PR info for a worktree path."""
    cache = _load_pr_cache()
    entry = cache.get(wt_path)
    if entry:
        return entry.get("pr")
    return None


def find_worktree(name: str, base: str = _DEFAULT_WORKTREE_BASE) -> str | None:
    """Find a single worktree by name (exact basename match or unique substring)."""
    matches = find_worktrees([name], base=base)
    if len(matches) == 1:
        return matches[0]
    return None


def find_worktrees(
    patterns: list[str],
    base: str = _DEFAULT_WORKTREE_BASE,
) -> list[str]:
    """Find worktrees matching any of the given patterns.

    Each pattern is tried as:
    1. Exact directory name
    2. Regex match against directory name
    3. Substring match (fallback)

    Returns deduplicated list of matching paths.
    """
    import re as _re

    base_expanded = os.path.expanduser(base)
    if not os.path.isdir(base_expanded):
        return []

    # Gather all worktree dir names
    all_dirs: list[tuple[str, str]] = []  # (name, full_path)
    with os.scandir(base_expanded) as entries:
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                all_dirs.append((entry.name, entry.path))

    matched: dict[str, str] = {}  # path -> path (dedup)
    for pattern in patterns:
        # Try exact match first
        exact = os.path.join(base_expanded, pattern)
        if os.path.isdir(exact):
            matched[exact] = exact
            continue

        # Try as regex
        try:
            regex = _re.compile(pattern)
            for dirname, dirpath in all_dirs:
                if regex.search(dirname):
                    matched[dirpath] = dirpath
            continue
        except _re.error:
            pass

        # Fallback: substring
        for dirname, dirpath in all_dirs:
            if pattern in dirname:
                matched[dirpath] = dirpath

    return sorted(matched.values())


def resume_worktree(
    name: str,
    *,
    base: str = _DEFAULT_WORKTREE_BASE,
    profile_override: str | None = None,
    continue_session: bool = False,
    jump: bool = True,
) -> dict:
    """Resume work in a single worktree - jump to existing session or create new one.

    Returns dict with action taken: {"action": "jumped"|"created"|"exists", ...}
    """
    wt_path = find_worktree(name, base=base)
    if not wt_path:
        raise RuntimeError(f"No worktree matching '{name}' found in {base}")

    return _resume_one(wt_path, profile_override=profile_override,
                       continue_session=continue_session, jump=jump)


def resume_worktrees(
    patterns: list[str],
    *,
    base: str = _DEFAULT_WORKTREE_BASE,
    profile_override: str | None = None,
    continue_session: bool = False,
) -> list[dict]:
    """Resume work in multiple worktrees matching patterns.

    Creates sessions for all matching worktrees (does not jump).
    Returns list of action dicts.
    """
    paths = find_worktrees(patterns, base=base)
    if not paths:
        raise RuntimeError(f"No worktrees matching patterns: {patterns}")

    results = []
    for wt_path in paths:
        result = _resume_one(wt_path, profile_override=profile_override,
                             continue_session=continue_session, jump=False)
        results.append(result)
    return results


def _resume_one(
    wt_path: str,
    *,
    profile_override: str | None = None,
    continue_session: bool = False,
    jump: bool = True,
) -> dict:
    """Resume a single worktree path."""
    from .core import session_exists, uniqueify_session_name, create_profile_session, jump_session

    # Check if there's already a session using this worktree
    sessions = list_sessions()
    for s in sessions:
        if s.working_dir == wt_path:
            if jump:
                jump_session(s.name)
            return {"action": "exists", "session": s.name, "worktree": wt_path}

    # Detect profile from branch name
    profile_name = profile_override
    if not profile_name:
        r = _run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=wt_path, timeout=5)
        branch = r.stdout.strip() if r.returncode == 0 else ""
        agent_type = _detect_agent_type(wt_path, branch)
        if agent_type == "codex":
            profile_name = "codex"
        else:
            profile_name = "claude"

    # Build agent override command if --continue
    # Appends --continue to the profile's configured command rather than hardcoding
    agent_override = None
    if continue_session and profile_name in ("claude", "codex"):
        from .core import resolve_session_profile
        profile = resolve_session_profile(profile_name)
        if profile and profile.command_parts:
            agent_override = " ".join(profile.command_parts) + " --continue"

    # Session name = worktree basename
    session_name = os.path.basename(wt_path)
    if session_exists(session_name):
        session_name = uniqueify_session_name(session_name)

    create_profile_session(
        session_name,
        profile_name=profile_name,
        agent=agent_override,
        directory=wt_path,
    )

    if jump:
        jump_session(session_name)
    return {"action": "created", "session": session_name, "worktree": wt_path, "profile": profile_name}


def refresh_worktree_prs(
    worktrees: list[WorktreeInfo] | None = None,
    *,
    base: str = _DEFAULT_WORKTREE_BASE,
    repo: str | None = None,
) -> list[dict]:
    """Fetch PR status for worktrees and cache results.

    Uses `gh pr list --head <branch>` per worktree, threaded for speed.
    Returns list of result dicts.
    """
    if worktrees is None:
        worktrees = scan_worktrees(base=base, repo=repo)

    cache = _load_pr_cache()

    def _fetch_pr(wt: WorktreeInfo) -> dict:
        if not wt.branch or wt.branch in ("main", "master"):
            return {"path": wt.path, "branch": wt.branch, "pr": None}

        # Need to run gh in the worktree dir for correct repo context
        result = _run_git(
            ["gh", "pr", "list", "--head", wt.branch, "--state", "all",
             "--json", "number,state,reviewDecision,mergeStateStatus", "--limit", "1"],
            cwd=wt.path, timeout=15,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {"path": wt.path, "branch": wt.branch, "pr": None}

        prs = _json.loads(result.stdout)
        if not prs:
            return {"path": wt.path, "branch": wt.branch, "pr": None}

        pr = prs[0]
        return {
            "path": wt.path,
            "branch": wt.branch,
            "pr": {
                "number": pr["number"],
                "state": pr["state"],
                "review": pr.get("reviewDecision") or "PENDING",
                "merge_state": pr.get("mergeStateStatus") or "UNKNOWN",
            }
        }

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_fetch_pr, worktrees))

    # Update cache
    for r in results:
        cache[r["path"]] = {"branch": r["branch"], "pr": r.get("pr")}
    _save_pr_cache(cache)

    return results


def clean_worktrees(worktrees: list[WorktreeInfo], *, dry_run: bool = True) -> list[dict]:
    """Remove worktrees that are merged OR (orphan AND stale).

    Uses remove_worktree() and delete_branch() from core.
    Returns action dicts describing what was done.
    """
    actions: list[dict] = []

    for wt in worktrees:
        should_clean = wt.is_merged or (wt.is_orphan and wt.is_stale)
        if not should_clean:
            continue

        action: dict = {
            "path": wt.path,
            "branch": wt.branch,
            "repo_name": wt.repo_name,
            "reason": "merged" if wt.is_merged else "orphan+stale",
            "removed": False,
            "branch_deleted": False,
            "dry_run": dry_run,
        }

        if not dry_run:
            # Resolve parent repo before removal (path won't exist after)
            repo_dir = _worktree_parent_repo(wt.path) or wt.path
            action["removed"] = remove_worktree(wt.path)
            if wt.branch and wt.branch not in ("main", "master") and action["removed"]:
                action["branch_deleted"] = delete_branch(repo_dir, wt.branch)

        actions.append(action)

    return actions
