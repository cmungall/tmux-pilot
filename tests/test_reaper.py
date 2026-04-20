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
    set_calls: list[tuple[str, str, str]] = []

    monkeypatch.setattr(reaper.core, "list_sessions", lambda **kwargs: [_session("alpha", branch="feat/alpha")])
    monkeypatch.setattr(
        reaper,
        "_gh_pr_status",
        lambda branch, *, repo_dir="": {"number": 42, "state": "MERGED", "review": "APPROVED", "merge_state": "CLEAN"},
    )
    monkeypatch.setattr(reaper.core, "_metadata_timestamp", lambda: "2026-04-19T22:15:00Z")
    monkeypatch.setattr(reaper.core, "set_metadata", lambda *args: set_calls.append(args))

    results = reaper.reap_sessions(dry_run=True)

    assert set_calls == [
        ("alpha", "pr", "42"),
        ("alpha", "pr_state", "MERGED"),
        ("alpha", "pr_review", "APPROVED"),
        ("alpha", "pr_merge_state", "CLEAN"),
        ("alpha", "last_refresh", "2026-04-19T22:15:00Z"),
    ]
    assert results == [
        {
            "session": "alpha",
            "branch": "feat/alpha",
            "pr": 42,
            "pr_state": "MERGED",
            "pr_review": "APPROVED",
            "pr_merge_state": "CLEAN",
            "last_refresh": "2026-04-19T22:15:00Z",
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

    monkeypatch.setattr(reaper.core, "list_sessions", lambda **kwargs: [_session("alpha", branch="feat/alpha")])
    monkeypatch.setattr(
        reaper,
        "_gh_pr_status",
        lambda branch, *, repo_dir="": {"number": 42, "state": "MERGED", "review": "APPROVED", "merge_state": "CLEAN"},
    )
    monkeypatch.setattr(reaper.core, "_metadata_timestamp", lambda: "2026-04-19T22:15:00Z")
    monkeypatch.setattr(reaper, "_has_uncommitted", lambda working_dir: False)
    monkeypatch.setattr(reaper.core, "set_metadata", lambda *args: set_calls.append(args))
    monkeypatch.setattr(reaper.core, "kill_session", lambda name: kill_calls.append(name))
    monkeypatch.setattr(reaper.core, "_is_git_worktree", lambda working_dir: True)
    monkeypatch.setattr(reaper.core, "_remove_worktree", lambda working_dir: True)
    monkeypatch.setattr(reaper.core, "_delete_branch", lambda repo, branch: True)

    results = reaper.reap_sessions()

    assert kill_calls == ["alpha"]
    assert set_calls == [
        ("alpha", "pr", "42"),
        ("alpha", "pr_state", "MERGED"),
        ("alpha", "pr_review", "APPROVED"),
        ("alpha", "pr_merge_state", "CLEAN"),
        ("alpha", "last_refresh", "2026-04-19T22:15:00Z"),
    ]
    assert results[0]["worktree_removed"] is True
    assert results[0]["branch_deleted"] is True


def test_reap_sessions_skips_uncommitted_changes(monkeypatch):
    monkeypatch.setattr(reaper.core, "list_sessions", lambda **kwargs: [_session("alpha", branch="feat/alpha")])
    monkeypatch.setattr(
        reaper,
        "_gh_pr_status",
        lambda branch, *, repo_dir="": {"number": 42, "state": "MERGED", "review": "APPROVED", "merge_state": "CLEAN"},
    )
    monkeypatch.setattr(reaper.core, "_metadata_timestamp", lambda: "2026-04-19T22:15:00Z")
    monkeypatch.setattr(reaper, "_has_uncommitted", lambda working_dir: True)
    monkeypatch.setattr(reaper.core, "set_metadata", lambda *args: None)

    results = reaper.reap_sessions()

    assert results == [
        {
            "session": "alpha",
            "branch": "feat/alpha",
            "pr": 42,
            "pr_state": "MERGED",
            "pr_review": "APPROVED",
            "pr_merge_state": "CLEAN",
            "last_refresh": "2026-04-19T22:15:00Z",
            "killed": False,
            "worktree_removed": False,
            "branch_deleted": False,
            "skipped": True,
            "reason": "uncommitted-changes",
        }
    ]


def test_reap_sessions_include_no_pr(monkeypatch):
    monkeypatch.setattr(reaper.core, "list_sessions", lambda **kwargs: [_session("alpha", branch="feat/alpha")])
    monkeypatch.setattr(reaper, "_gh_pr_status", lambda branch, *, repo_dir="": None)
    monkeypatch.setattr(reaper.core, "_metadata_timestamp", lambda: "2026-04-19T22:15:00Z")
    monkeypatch.setattr(reaper, "_has_uncommitted", lambda working_dir: False)
    monkeypatch.setattr(reaper.core, "set_metadata", lambda *args: None)
    monkeypatch.setattr(reaper.core, "kill_session", lambda name: None)
    monkeypatch.setattr(reaper.core, "_is_git_worktree", lambda working_dir: False)
    monkeypatch.setattr(reaper.core, "_delete_branch", lambda repo, branch: False)

    results = reaper.reap_sessions(include_no_pr=True)

    assert results[0]["reason"] == "no-pr"
    assert results[0]["killed"] is True


def test_refresh_pr_metadata_updates_fields(monkeypatch):
    set_calls: list[tuple[str, str, str]] = []

    monkeypatch.setattr(reaper.core, "list_sessions", lambda **kwargs: [_session("alpha", branch="feat/alpha")])
    monkeypatch.setattr(
        reaper,
        "_gh_pr_status",
        lambda branch, *, repo_dir="": {"number": 42, "state": "OPEN", "review": "APPROVED", "merge_state": "CLEAN"},
    )
    monkeypatch.setattr(reaper.core, "_metadata_timestamp", lambda: "2026-04-19T22:15:00Z")
    monkeypatch.setattr(reaper.core, "set_metadata", lambda *args: set_calls.append(args))

    results = reaper.refresh_pr_metadata()

    assert set_calls == [
        ("alpha", "pr", "42"),
        ("alpha", "pr_state", "OPEN"),
        ("alpha", "pr_review", "APPROVED"),
        ("alpha", "pr_merge_state", "CLEAN"),
        ("alpha", "last_refresh", "2026-04-19T22:15:00Z"),
    ]
    assert results == [
        {
            "session": "alpha",
            "branch": "feat/alpha",
            "pr": 42,
            "pr_state": "OPEN",
            "pr_review": "APPROVED",
            "pr_merge_state": "CLEAN",
            "last_refresh": "2026-04-19T22:15:00Z",
            "skipped": False,
            "reason": "pr-open",
        }
    ]


def test_refresh_pr_metadata_queries_in_session_repo_context(monkeypatch):
    repo_dirs: list[str] = []

    monkeypatch.setattr(
        reaper.core,
        "list_sessions",
        lambda **kwargs: [_session("alpha", branch="feat/alpha", repo="/repo/root")],
    )

    def fake_gh_pr_status(branch: str, *, repo_dir: str = ""):
        repo_dirs.append(repo_dir)
        return {"number": 42, "state": "OPEN", "review": "APPROVED", "merge_state": "CLEAN"}

    monkeypatch.setattr(reaper, "_gh_pr_status", fake_gh_pr_status)
    monkeypatch.setattr(reaper.core, "_metadata_timestamp", lambda: "2026-04-19T22:15:00Z")
    monkeypatch.setattr(reaper.core, "set_metadata", lambda *args: None)

    reaper.refresh_pr_metadata()

    assert repo_dirs == ["/tmp/alpha"]


def test_refresh_pr_metadata_passes_repo_filter_to_list_sessions(monkeypatch):
    repo_filters: list[str | None] = []

    def list_sessions(*, status=None, repo=None, process=None):
        del status, process
        repo_filters.append(repo)
        return [_session("alpha", branch="feat/alpha")]

    monkeypatch.setattr(reaper.core, "list_sessions", list_sessions)
    monkeypatch.setattr(
        reaper,
        "_gh_pr_status",
        lambda branch, *, repo_dir="": {"number": 42, "state": "OPEN", "review": "APPROVED", "merge_state": "CLEAN"},
    )
    monkeypatch.setattr(reaper.core, "_metadata_timestamp", lambda: "2026-04-19T22:15:00Z")
    monkeypatch.setattr(reaper.core, "set_metadata", lambda *args: None)

    reaper.refresh_pr_metadata(repo="dismech")

    assert repo_filters == ["dismech"]


def test_refresh_pr_metadata_clears_stale_fields_when_no_pr(monkeypatch):
    set_calls: list[tuple[str, str, str]] = []

    monkeypatch.setattr(
        reaper.core,
        "list_sessions",
        lambda **kwargs: [_session("alpha", branch="feat/alpha", pr="42", pr_state="OPEN")],
    )
    monkeypatch.setattr(reaper, "_gh_pr_status", lambda branch, *, repo_dir="": None)
    monkeypatch.setattr(reaper.core, "_metadata_timestamp", lambda: "2026-04-19T22:15:00Z")
    monkeypatch.setattr(reaper.core, "set_metadata", lambda *args: set_calls.append(args))

    results = reaper.refresh_pr_metadata()

    assert set_calls == [
        ("alpha", "pr", ""),
        ("alpha", "pr_state", ""),
        ("alpha", "pr_review", ""),
        ("alpha", "pr_merge_state", ""),
        ("alpha", "last_refresh", "2026-04-19T22:15:00Z"),
    ]
    assert results[0]["pr"] is None
    assert results[0]["pr_state"] is None
    assert results[0]["reason"] == "no-pr"
