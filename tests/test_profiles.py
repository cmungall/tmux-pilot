"""Tests for profile-backed session creation and repo bootstrapping."""

from __future__ import annotations

import subprocess

from pathlib import Path

from tmux_pilot import core


def test_resolve_session_profile_merges_default_values_and_builtins(tmp_path):
    config = tmp_path / "profiles.toml"
    config.write_text(
        """
[default]
extends = "claude"
worktree_base = "~/worktrees"

[dismech]
repo = "~/repos/dismech"
branch_prefix = "fix"
"""
    )

    profile = core.resolve_session_profile("dismech", issue=771, path=config)

    assert profile is not None
    assert profile.repo == "~/repos/dismech"
    assert profile.command_parts == ("claude", "--permission-mode", "bypassPermissions")
    assert profile.worktree_base == "~/worktrees"
    assert profile.branch_prefix == "fix"


def test_builtin_profiles_can_be_customized_from_config(tmp_path):
    config = tmp_path / "profiles.toml"
    config.write_text(
        """
[profiles.codex]
command = ["codex", "--profile", "safe"]
"""
    )

    profile = core.resolve_session_profile("codex", path=config)

    assert profile is not None
    assert profile.command_parts == ("codex", "--profile", "safe")


def test_create_profile_session_creates_worktree_launches_agent_and_prompt(monkeypatch, tmp_path):
    profile = core.SessionProfile(
        name="pi",
        repo="~/repos/dismech",
        command=("pi", "--session-dir", "{session_dir}"),
        worktree_base=str(tmp_path),
        branch_prefix="fix",
        prompt_wait_timeout=12.0,
    )
    metadata_calls: list[tuple[str, str, str]] = []
    send_calls: list[tuple[str, str]] = []
    new_calls: list[tuple[str, str | None, str | None, str | None]] = []
    wait_calls: list[tuple[str, float, float]] = []

    repo_path = str(Path("~/repos/dismech").expanduser().resolve())
    worktree_dir = tmp_path / "dismech-review-wilson"

    monkeypatch.setattr(core, "resolve_session_profile", lambda *args, **kwargs: profile)
    monkeypatch.setattr(core, "_fetch_issue_title", lambda repo_path, issue_number: "Review Wilson")
    monkeypatch.setattr(
        core,
        "_create_bootstrap_workspace",
        lambda **kwargs: {
            "repo": repo_path,
            "worktree": str(worktree_dir),
            "branch": "fix/771-review-wilson",
            "base_ref": "origin/main",
        },
    )
    monkeypatch.setattr(
        core,
        "new_session",
        lambda name, *, directory=None, desc=None, command=None: new_calls.append((name, directory, desc, command)),
    )
    monkeypatch.setattr(core, "set_metadata", lambda *args: metadata_calls.append(args))
    monkeypatch.setattr(core, "send_keys", lambda session_name, text: send_calls.append((session_name, text)))

    def fake_wait(name: str, *, timeout: float, interval: float = 0.25):
        wait_calls.append((name, timeout, interval))
        return {"type": "pi", "state": "idle", "ready": True}

    monkeypatch.setattr(core, "wait_until_session_ready", fake_wait)

    result = core.create_profile_session(
        "review-wilson",
        profile_name="pi",
        issue=771,
        prompt="Summarize the issue and propose a fix.",
    )

    assert new_calls == [
        (
            "review-wilson",
            str(worktree_dir),
            "Review Wilson",
            f"pi --session-dir {worktree_dir}/.tmux-pilot/pi/sessions",
        )
    ]
    assert metadata_calls == [
        ("review-wilson", "task", "review-wilson"),
        ("review-wilson", "repo", repo_path),
        ("review-wilson", "branch", "fix/771-review-wilson"),
        ("review-wilson", "status", "active"),
        ("review-wilson", "desc", "Review Wilson"),
    ]
    assert send_calls == [("review-wilson", "Summarize the issue and propose a fix.")]
    assert wait_calls == [("review-wilson", 12.0, 0.25)]
    assert result["branch"] == "fix/771-review-wilson"
    assert result["worktree"] == str(worktree_dir)


def test_create_profile_session_launches_agent_in_directory_without_bootstrap(monkeypatch, tmp_path):
    profile = core.SessionProfile(
        name="codex",
        command=("codex", "--profile", "yolo"),
    )
    metadata_calls: list[tuple[str, str, str]] = []
    send_calls: list[tuple[str, str]] = []
    new_calls: list[tuple[str, str | None, str | None, str | None]] = []

    monkeypatch.setattr(core, "resolve_session_profile", lambda *args, **kwargs: profile)
    monkeypatch.setattr(
        core,
        "new_session",
        lambda name, *, directory=None, desc=None, command=None: new_calls.append((name, directory, desc, command)),
    )
    monkeypatch.setattr(core, "set_metadata", lambda *args: metadata_calls.append(args))
    monkeypatch.setattr(core, "send_keys", lambda session_name, text: send_calls.append((session_name, text)))
    monkeypatch.setattr(core, "_git_root", lambda path: "")
    monkeypatch.setattr(core, "_detect_git_branch", lambda path: "")

    result = core.create_profile_session(
        "local-task",
        profile_name="codex",
        directory=str(tmp_path),
    )

    assert new_calls == [("local-task", str(tmp_path.resolve()), None, "codex --profile yolo")]
    assert metadata_calls == [
        ("local-task", "task", "local-task"),
        ("local-task", "status", "active"),
    ]
    assert send_calls == []
    assert result["worktree"] == str(tmp_path.resolve())


def test_resolve_repo_source_clones_github_repo_when_missing(monkeypatch, tmp_path):
    clone_calls: list[tuple[list[str], str | None]] = []

    def fake_run(
        args: list[str],
        *,
        check: bool = True,
        capture: bool = True,
        cwd: str | None = None,
        timeout: int = 5,
    ) -> subprocess.CompletedProcess[str]:
        del check, capture, timeout
        clone_calls.append((args, cwd))
        Path(args[-1]).mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(core, "_run", fake_run)

    resolved = core._resolve_repo_source("acme/widgets", clone_base=str(tmp_path))

    assert resolved == str((tmp_path / "widgets").resolve())
    assert clone_calls == [
        (["git", "clone", "https://github.com/acme/widgets.git", str(tmp_path / "widgets")], str(tmp_path))
    ]


def test_list_sessions_detects_branch_from_worktree(monkeypatch):
    monkeypatch.setattr(core, "tmux_running", lambda: True)
    monkeypatch.setattr(
        core,
        "_tmux",
        lambda *args, **kwargs: "alpha\tzsh\t/tmp/alpha\t1234\t\t\t\t\t\t\t\t\t\t",
    )
    monkeypatch.setattr(core, "_detect_git_branch", lambda path: "feat/detected")

    sessions = core.list_sessions()

    assert len(sessions) == 1
    assert sessions[0].metadata["branch"] == "feat/detected"
