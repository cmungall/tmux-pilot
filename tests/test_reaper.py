"""Tests for PR-based reaping logic."""

from __future__ import annotations

from tmux_pilot import core, reaper


def _session(name: str, **metadata: str) -> core.SessionInfo:
    return core.SessionInfo(
        name=name,
        process="claude-code",
        working_dir=f"/tmp/{name}",
        metadata=metadata,
    )


def test_reap_sessions_dry_run_for_merged_pr(monkeypatch):
    monkeypatch.setattr(reaper.core, "list_sessions", lambda: [_session("alpha", branch="feat/alpha")])
    monkeypatch.setattr(reaper, "_gh_pr_status", lambda branch: {"number": 42, "state": "MERGED"})

    results = reaper.reap_sessions(dry_run=True)

    assert results == [
        {
            "session": "alpha",
            "branch": "feat/alpha",
            "pr": 42,
            "pr_state": "MERGED",
            "killed": False,
            "worktree_removed": False,
            "branch_deleted": False,
            "skipped": False,
            "reason": "pr-merged",
            "action": "confirm",
        }
    ]


def test_reap_sessions_updates_metadata_and_cleans(monkeypatch):
    set_calls: list[tuple[str, str, str]] = []
    kill_calls: list[str] = []

    monkeypatch.setattr(reaper.core, "list_sessions", lambda: [_session("alpha", branch="feat/alpha")])
    monkeypatch.setattr(reaper, "_gh_pr_status", lambda branch: {"number": 42, "state": "MERGED"})
    monkeypatch.setattr(reaper, "_has_uncommitted", lambda working_dir: False)
    monkeypatch.setattr(reaper.core, "set_metadata", lambda *args: set_calls.append(args))
    monkeypatch.setattr(reaper.core, "kill_session", lambda name: kill_calls.append(name))
    monkeypatch.setattr(reaper.core, "_is_git_worktree", lambda working_dir: True)
    monkeypatch.setattr(reaper.core, "_remove_worktree", lambda working_dir: True)
    monkeypatch.setattr(reaper.core, "_delete_branch", lambda repo, branch: True)

    results = reaper.reap_sessions()

    assert kill_calls == ["alpha"]
    assert set_calls == [("alpha", "pr", "42"), ("alpha", "pr_state", "MERGED")]
    assert results[0]["worktree_removed"] is True
    assert results[0]["branch_deleted"] is True


def test_reap_sessions_skips_uncommitted_changes(monkeypatch):
    monkeypatch.setattr(reaper.core, "list_sessions", lambda: [_session("alpha", branch="feat/alpha")])
    monkeypatch.setattr(reaper, "_gh_pr_status", lambda branch: {"number": 42, "state": "MERGED"})
    monkeypatch.setattr(reaper, "_has_uncommitted", lambda working_dir: True)
    monkeypatch.setattr(reaper.core, "set_metadata", lambda *args: None)

    results = reaper.reap_sessions()

    assert results == [
        {
            "session": "alpha",
            "branch": "feat/alpha",
            "pr": 42,
            "pr_state": "MERGED",
            "killed": False,
            "worktree_removed": False,
            "branch_deleted": False,
            "skipped": True,
            "reason": "uncommitted-changes",
        }
    ]


def test_reap_sessions_include_no_pr(monkeypatch):
    monkeypatch.setattr(reaper.core, "list_sessions", lambda: [_session("alpha", branch="feat/alpha")])
    monkeypatch.setattr(reaper, "_gh_pr_status", lambda branch: None)
    monkeypatch.setattr(reaper, "_has_uncommitted", lambda working_dir: False)
    monkeypatch.setattr(reaper.core, "kill_session", lambda name: None)
    monkeypatch.setattr(reaper.core, "_is_git_worktree", lambda working_dir: False)
    monkeypatch.setattr(reaper.core, "_delete_branch", lambda repo, branch: False)

    results = reaper.reap_sessions(include_no_pr=True)

    assert results[0]["reason"] == "no-pr"
    assert results[0]["killed"] is True
