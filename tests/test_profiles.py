"""Tests for profile-backed session creation."""

from __future__ import annotations

from pathlib import Path

from tmux_pilot import core


def test_resolve_session_profile_merges_default_values(tmp_path):
    config = tmp_path / "profiles.toml"
    config.write_text(
        """
[default]
agent = "claude"
agent_args = "--permission-mode bypassPermissions"
worktree_base = "~/worktrees"

[dismech]
repo = "~/repos/dismech"
branch_prefix = "fix"
"""
    )

    profile = core.resolve_session_profile("dismech", issue=771, path=config)

    assert profile is not None
    assert profile.repo == "~/repos/dismech"
    assert profile.agent == "claude"
    assert profile.agent_args == "--permission-mode bypassPermissions"
    assert profile.worktree_base == "~/worktrees"
    assert profile.branch_prefix == "fix"


def test_create_profile_session_creates_worktree_launches_agent_and_prompt(monkeypatch, tmp_path):
    profile = core.SessionProfile(
        name="dismech",
        repo="~/repos/dismech",
        agent="codex",
        agent_args="--profile yolo",
        worktree_base=str(tmp_path),
        branch_prefix="fix",
    )
    git_calls: list[tuple[list[str], str]] = []
    metadata_calls: list[tuple[str, str, str]] = []
    send_calls: list[tuple[str, str]] = []
    new_calls: list[tuple[str, str | None, str | None]] = []
    sleep_calls: list[int] = []

    monkeypatch.setattr(core, "resolve_session_profile", lambda *args, **kwargs: profile)
    monkeypatch.setattr(core, "_fetch_issue_title", lambda repo_path, issue_number: "Review Wilson")
    monkeypatch.setattr(core, "_git", lambda args, *, cwd, check=True, timeout=15: git_calls.append((args, cwd)) or "")
    monkeypatch.setattr(
        core,
        "new_session",
        lambda name, *, directory=None, desc=None: new_calls.append((name, directory, desc)),
    )
    monkeypatch.setattr(core, "set_metadata", lambda *args: metadata_calls.append(args))
    monkeypatch.setattr(core, "send_keys", lambda session_name, text: send_calls.append((session_name, text)))
    monkeypatch.setattr(core.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    result = core.create_profile_session(
        "review-wilson",
        profile_name="dismech",
        issue=771,
        prompt="Summarize the issue and propose a fix.",
    )

    repo_path = str(Path("~/repos/dismech").expanduser().resolve())
    worktree_dir = tmp_path / "dismech-review-wilson"

    assert git_calls == [
        (["fetch", "origin"], repo_path),
        (["worktree", "add", "-b", "fix/771-review-wilson", str(worktree_dir), "origin/main"], repo_path),
    ]
    assert new_calls == [("review-wilson", str(worktree_dir), "Review Wilson")]
    assert metadata_calls == [
        ("review-wilson", "repo", repo_path),
        ("review-wilson", "branch", "fix/771-review-wilson"),
        ("review-wilson", "status", "active"),
        ("review-wilson", "desc", "Review Wilson"),
    ]
    assert send_calls == [
        ("review-wilson", "codex --profile yolo"),
        ("review-wilson", "Summarize the issue and propose a fix."),
    ]
    assert sleep_calls == [5]
    assert result["branch"] == "fix/771-review-wilson"
    assert result["worktree"] == str(worktree_dir)


def test_list_sessions_detects_branch_from_worktree(monkeypatch):
    monkeypatch.setattr(core, "tmux_running", lambda: True)
    monkeypatch.setattr(
        core,
        "_tmux",
        lambda *args, **kwargs: "alpha\tzsh\t/tmp/alpha\t\t\t\t\t\t\t\t\t",
    )
    monkeypatch.setattr(core, "_detect_git_branch", lambda path: "feat/detected")

    sessions = core.list_sessions()

    assert len(sessions) == 1
    assert sessions[0].metadata["branch"] == "feat/detected"
