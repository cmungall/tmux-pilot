"""Reap tmux sessions whose PRs are merged."""

from __future__ import annotations

import json
import subprocess

from . import core


def _gh_pr_status(branch: str, *, repo_dir: str = "") -> dict | None:
    """Query GitHub for PR status on a branch.

    Returns dict with number/state/review/merge_state, or None if no PR found.
    """
    result = subprocess.run(
        ["gh", "pr", "list", "--head", branch, "--state", "all",
         "--json", "number,state,reviewDecision,mergeStateStatus", "--limit", "1"],
        capture_output=True, text=True, timeout=15, cwd=repo_dir or None,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    prs = json.loads(result.stdout)
    if not prs:
        return None
    pr = prs[0]
    return {
        "number": pr["number"],
        "state": pr["state"],
        "review": pr.get("reviewDecision") or "PENDING",
        "merge_state": pr.get("mergeStateStatus") or "UNKNOWN",
    }


def _has_uncommitted(working_dir: str) -> bool:
    """Check if a working directory has uncommitted changes."""
    result = subprocess.run(
        ["git", "-C", working_dir, "status", "--porcelain"],
        capture_output=True, text=True, timeout=5,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _is_inside_git_worktree(working_dir: str) -> bool:
    """True if *working_dir* is inside any git work tree."""
    if not working_dir:
        return False
    result = subprocess.run(
        ["git", "-C", working_dir, "rev-parse", "--is-inside-work-tree"],
        capture_output=True, text=True, timeout=5,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _is_dead_session(session: core.SessionInfo) -> bool:
    """A bare, branchless session whose cwd is no longer inside a git work tree.

    These are typically sessions whose worktree was removed out from under them:
    the shell's cwd falls back to ``$HOME``. There is nothing to reap but the
    session itself — no PR, no branch, no worktree — so reaping kills only the
    tmux session and never touches disk.
    """
    return not _is_inside_git_worktree(session.working_dir)


def _dead_session_action(session: core.SessionInfo, *, dry_run: bool) -> dict:
    """Build (and, unless dry-run, perform) the reap of a dead orphan session."""
    action: dict = {
        "session": session.name,
        "branch": "",
        "pr": None,
        "pr_state": None,
        "pr_review": None,
        "pr_merge_state": None,
        "last_refresh": None,
        "killed": False,
        "worktree_removed": False,
        "branch_deleted": False,
        "skipped": False,
        "reason": "dead-session",
    }
    if dry_run:
        action["action"] = "confirm"
        return action
    core.kill_session(session.name)
    action["killed"] = True
    return action


def _resolve_sessions(
    names: list[str] | None = None,
    *,
    repo: str | None = None,
) -> list[core.SessionInfo]:
    """Return all sessions or a named subset, preserving the requested order."""
    return core.resolve_sessions(names=names, repo=repo)


def _refresh_session_pr_metadata(session: core.SessionInfo) -> dict:
    """Refresh and persist cached PR metadata for a single session."""
    branch = session.metadata.get("branch", "")
    repo_dir = session.working_dir or session.metadata.get("repo", "")
    action: dict = {
        "session": session.name,
        "branch": branch,
        "pr": None,
        "pr_state": None,
        "pr_review": None,
        "pr_merge_state": None,
        "last_refresh": None,
        "skipped": False,
        "reason": "",
    }

    if not branch:
        action["skipped"] = True
        action["reason"] = "no-branch"
        return action

    pr_info = _gh_pr_status(branch, repo_dir=repo_dir)
    refreshed_at = core._metadata_timestamp()

    core.set_metadata(session.name, "pr", str(pr_info["number"]) if pr_info else "")
    core.set_metadata(session.name, "pr_state", pr_info["state"] if pr_info else "")
    core.set_metadata(session.name, "pr_review", pr_info["review"] if pr_info else "")
    core.set_metadata(session.name, "pr_merge_state", pr_info["merge_state"] if pr_info else "")
    core.set_metadata(session.name, "last_refresh", refreshed_at)

    action.update(
        {
            "pr": pr_info["number"] if pr_info else None,
            "pr_state": pr_info["state"] if pr_info else None,
            "pr_review": pr_info["review"] if pr_info else None,
            "pr_merge_state": pr_info["merge_state"] if pr_info else None,
            "last_refresh": refreshed_at,
            "reason": f"pr-{pr_info['state'].lower()}" if pr_info else "no-pr",
        }
    )
    return action


def refresh_pr_metadata(
    *,
    names: list[str] | None = None,
    repo: str | None = None,
) -> list[dict]:
    """Refresh cached PR metadata for all sessions or a named subset."""
    return [_refresh_session_pr_metadata(session) for session in _resolve_sessions(names, repo=repo)]


def reap_sessions(
    *,
    dry_run: bool = False,
    force: bool = False,
    include_no_pr: bool = False,
    include_dead: bool = False,
) -> list[dict]:
    """Identify and reap sessions whose PRs are merged.

    For each session with a branch, queries GitHub PR status.
    MERGED PRs trigger reaping (kill session, remove worktree, delete branch).
    Sessions with uncommitted changes are skipped unless --force.

    With ``include_dead``, bare branchless sessions whose cwd is no longer inside
    a git work tree (a worktree removed out from under the session) are also
    reaped — killing the session only, since there is nothing on disk to remove.

    Returns list of action dicts.
    """
    sessions = core.list_sessions()
    results: list[dict] = []

    for s in sessions:
        refresh = _refresh_session_pr_metadata(s)
        branch = refresh.get("branch", "")
        if refresh.get("reason") == "no-branch":
            if include_dead and _is_dead_session(s):
                results.append(_dead_session_action(s, dry_run=dry_run))
            continue

        working_dir = s.working_dir

        action: dict = {
            "session": s.name,
            "branch": branch,
            "pr": refresh["pr"],
            "pr_state": refresh["pr_state"],
            "pr_review": refresh["pr_review"],
            "pr_merge_state": refresh["pr_merge_state"],
            "last_refresh": refresh["last_refresh"],
            "killed": False,
            "worktree_removed": False,
            "branch_deleted": False,
            "skipped": False,
            "reason": "",
        }

        # Decide whether to reap
        if refresh["pr_state"] == "MERGED":
            action["reason"] = "pr-merged"
        elif refresh["pr"] is None and include_no_pr:
            action["reason"] = "no-pr"
        else:
            if refresh["pr"]:
                action["reason"] = str(refresh["reason"])
            else:
                action["reason"] = "no-pr"
            action["skipped"] = True
            # Only include in results if it would be actionable
            if not include_no_pr and refresh["pr"] is None:
                continue
            results.append(action)
            continue

        # Check for uncommitted changes
        if working_dir and _has_uncommitted(working_dir) and not force:
            action["skipped"] = True
            action["reason"] = "uncommitted-changes"
            results.append(action)
            continue

        if dry_run:
            action["action"] = "confirm"
            results.append(action)
            continue

        # Actually reap
        core.kill_session(s.name)
        action["killed"] = True

        if working_dir and core._is_git_worktree(working_dir):
            action["worktree_removed"] = core._remove_worktree(working_dir)

        if branch and working_dir:
            repo = s.metadata.get("repo", working_dir)
            action["branch_deleted"] = core._delete_branch(repo, branch)

        results.append(action)

    return results
