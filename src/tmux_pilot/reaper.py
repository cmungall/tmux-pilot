"""Reap tmux sessions whose PRs are merged."""

from __future__ import annotations

import json
import subprocess

from . import core


def _gh_pr_status(branch: str) -> dict | None:
    """Query GitHub for PR status on a branch.

    Returns dict with 'number' and 'state', or None if no PR found.
    """
    result = subprocess.run(
        ["gh", "pr", "list", "--head", branch, "--state", "all",
         "--json", "number,state", "--limit", "1"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    prs = json.loads(result.stdout)
    if not prs:
        return None
    return {"number": prs[0]["number"], "state": prs[0]["state"]}


def _has_uncommitted(working_dir: str) -> bool:
    """Check if a working directory has uncommitted changes."""
    result = subprocess.run(
        ["git", "-C", working_dir, "status", "--porcelain"],
        capture_output=True, text=True, timeout=5,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def reap_sessions(
    *,
    dry_run: bool = False,
    force: bool = False,
    include_no_pr: bool = False,
) -> list[dict]:
    """Identify and reap sessions whose PRs are merged.

    For each session with a branch, queries GitHub PR status.
    MERGED PRs trigger reaping (kill session, remove worktree, delete branch).
    Sessions with uncommitted changes are skipped unless --force.

    Returns list of action dicts.
    """
    sessions = core.list_sessions()
    results: list[dict] = []

    for s in sessions:
        branch = s.metadata.get("branch", "")
        if not branch:
            continue

        working_dir = s.working_dir

        # Query PR status
        pr_info = _gh_pr_status(branch)

        # Cache PR info on the session
        if pr_info and not dry_run:
            core.set_metadata(s.name, "pr", str(pr_info["number"]))
            core.set_metadata(s.name, "pr_state", pr_info["state"])

        action: dict = {
            "session": s.name,
            "branch": branch,
            "pr": pr_info["number"] if pr_info else None,
            "pr_state": pr_info["state"] if pr_info else None,
            "killed": False,
            "worktree_removed": False,
            "branch_deleted": False,
            "skipped": False,
            "reason": "",
        }

        # Decide whether to reap
        if pr_info and pr_info["state"] == "MERGED":
            action["reason"] = "pr-merged"
        elif not pr_info and include_no_pr:
            action["reason"] = "no-pr"
        else:
            if pr_info:
                action["reason"] = f"pr-{pr_info['state'].lower()}"
            else:
                action["reason"] = "no-pr"
            action["skipped"] = True
            # Only include in results if it would be actionable
            if not include_no_pr and not pr_info:
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
