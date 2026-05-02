"""Tests for tmux_pilot.worktree module."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import pytest

from tmux_pilot.worktree import (
    WorktreeInfo,
    scan_worktrees,
    worktree_summary,
    clean_worktrees,
    _read_repo_name,
    _detect_agent_type,
)
from tmux_pilot.cli import main as cli_main


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_wt(
    path="/tmp/wt/branch-a",
    repo_name="myrepo",
    branch="branch-a",
    age_days=1.0,
    has_session=True,
    session_name="sess-a",
    agent_type="claude",
    is_merged=False,
    has_unpushed=False,
    has_uncommitted=False,
    last_commit_date=None,
) -> WorktreeInfo:
    if last_commit_date is None:
        last_commit_date = datetime.now(timezone.utc) - timedelta(days=age_days)
    return WorktreeInfo(
        path=path,
        repo_name=repo_name,
        branch=branch,
        last_commit_date=last_commit_date,
        age_days=age_days,
        has_session=has_session,
        session_name=session_name,
        agent_type=agent_type,
        is_merged=is_merged,
        has_unpushed=has_unpushed,
        has_uncommitted=has_uncommitted,
    )


# ---------------------------------------------------------------------------
# WorktreeInfo properties
# ---------------------------------------------------------------------------


class TestWorktreeInfoProperties:
    def test_is_orphan_true_when_no_session(self):
        wt = _make_wt(has_session=False)
        assert wt.is_orphan is True

    def test_is_orphan_false_when_has_session(self):
        wt = _make_wt(has_session=True)
        assert wt.is_orphan is False

    def test_is_stale_true_when_old(self):
        wt = _make_wt(age_days=10.0)
        assert wt.is_stale is True

    def test_is_stale_false_when_recent(self):
        wt = _make_wt(age_days=3.0)
        assert wt.is_stale is False

    def test_is_stale_boundary(self):
        wt = _make_wt(age_days=7.0)
        assert wt.is_stale is False  # >7 required, not >=7

    def test_to_dict_keys(self):
        wt = _make_wt()
        d = wt.to_dict()
        expected_keys = {
            "path", "repo_name", "branch", "last_commit_date",
            "age_days", "has_session", "session_name", "agent_type",
            "is_merged", "has_unpushed", "has_uncommitted",
            "is_orphan", "is_stale",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_values(self):
        wt = _make_wt(path="/tmp/x", repo_name="r", branch="b", age_days=2.5)
        d = wt.to_dict()
        assert d["path"] == "/tmp/x"
        assert d["repo_name"] == "r"
        assert d["branch"] == "b"
        assert d["age_days"] == 2.5
        assert d["is_orphan"] is False
        assert d["is_stale"] is False


# ---------------------------------------------------------------------------
# _read_repo_name
# ---------------------------------------------------------------------------


class TestReadRepoName:
    def test_reads_repo_from_gitdir(self, tmp_path):
        wt_dir = tmp_path / "feature-branch"
        wt_dir.mkdir()
        git_file = wt_dir / ".git"
        git_file.write_text("gitdir: /home/user/repos/myrepo/.git/worktrees/feature-branch\n")
        assert _read_repo_name(str(wt_dir)) == "myrepo"

    def test_nested_path(self, tmp_path):
        wt_dir = tmp_path / "fix-123"
        wt_dir.mkdir()
        git_file = wt_dir / ".git"
        git_file.write_text("gitdir: /a/b/c/coolproject/.git/worktrees/fix-123\n")
        assert _read_repo_name(str(wt_dir)) == "coolproject"

    def test_falls_back_to_dirname_when_no_git_file(self, tmp_path):
        wt_dir = tmp_path / "my-worktree"
        wt_dir.mkdir()
        assert _read_repo_name(str(wt_dir)) == "my-worktree"

    def test_falls_back_when_git_is_directory(self, tmp_path):
        wt_dir = tmp_path / "some-wt"
        wt_dir.mkdir()
        (wt_dir / ".git").mkdir()
        assert _read_repo_name(str(wt_dir)) == "some-wt"


# ---------------------------------------------------------------------------
# _detect_agent_type
# ---------------------------------------------------------------------------


class TestDetectAgentType:
    def test_codex_branch_prefix(self, tmp_path):
        assert _detect_agent_type(str(tmp_path), branch="codex/fix-thing") == "codex"

    def test_claude_branch_prefix(self, tmp_path):
        assert _detect_agent_type(str(tmp_path), branch="claude/add-feature") == "claude"

    def test_codex_dir_without_branch(self, tmp_path):
        (tmp_path / ".codex").mkdir()
        assert _detect_agent_type(str(tmp_path)) == "codex"

    def test_claude_dir_alone_is_not_enough(self, tmp_path):
        # .claude/ is often checked into repos, so it's not a reliable signal
        (tmp_path / ".claude").mkdir()
        assert _detect_agent_type(str(tmp_path)) == "unknown"

    def test_returns_unknown_when_no_signal(self, tmp_path):
        assert _detect_agent_type(str(tmp_path)) == "unknown"

    def test_codex_branch_overrides_claude_dir(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        assert _detect_agent_type(str(tmp_path), branch="codex/fix-thing") == "codex"


# ---------------------------------------------------------------------------
# scan_worktrees
# ---------------------------------------------------------------------------


class TestScanWorktrees:
    def test_returns_empty_for_nonexistent_base(self):
        result = scan_worktrees("/nonexistent/path/xyz123")
        assert result == []

    def test_returns_empty_for_empty_dir(self, tmp_path):
        result = scan_worktrees(str(tmp_path))
        assert result == []

    def test_skips_dirs_without_git_file(self, tmp_path):
        (tmp_path / "some-dir").mkdir()
        result = scan_worktrees(str(tmp_path))
        assert result == []

    def test_scans_worktrees(self, tmp_path, monkeypatch):
        # Create a fake worktree with .codex dir (reliable signal)
        wt_dir = tmp_path / "feature-x"
        wt_dir.mkdir()
        (wt_dir / ".git").write_text("gitdir: /repos/myrepo/.git/worktrees/feature-x\n")
        (wt_dir / ".codex").mkdir()

        # Mock _probe_worktree to avoid real git commands
        import subprocess as _sp

        dt = datetime.now(timezone.utc).isoformat()

        def fake_run_git(args, *, cwd=None, timeout=10):
            if "log" in args and "--format=%D%n%aI" in args:
                return _sp.CompletedProcess(args, 0, stdout=f"HEAD -> feature-x\n{dt}\n", stderr="")
            if "status" in args:
                return _sp.CompletedProcess(args, 0, stdout="", stderr="")
            return _sp.CompletedProcess(args, 1, stdout="", stderr="")

        monkeypatch.setattr("tmux_pilot.worktree._run_git", fake_run_git)
        monkeypatch.setattr("tmux_pilot.worktree.list_sessions", lambda: [])

        result = scan_worktrees(str(tmp_path))
        assert len(result) == 1
        assert result[0].repo_name == "myrepo"
        assert result[0].branch == "feature-x"
        assert result[0].agent_type == "codex"
        assert result[0].is_orphan is True

    def test_repo_filter(self, tmp_path, monkeypatch):
        # Two worktrees, different repos
        for name, repo in [("wt-a", "repoA"), ("wt-b", "repoB")]:
            d = tmp_path / name
            d.mkdir()
            (d / ".git").write_text(f"gitdir: /repos/{repo}/.git/worktrees/{name}\n")

        import subprocess as _sp

        dt = datetime.now(timezone.utc).isoformat()

        def fake_run_git(args, *, cwd=None, timeout=10):
            if "log" in args and "--format=%D%n%aI" in args:
                return _sp.CompletedProcess(args, 0, stdout=f"HEAD -> main\n{dt}\n", stderr="")
            if "status" in args:
                return _sp.CompletedProcess(args, 0, stdout="", stderr="")
            return _sp.CompletedProcess(args, 1, stdout="", stderr="")

        monkeypatch.setattr("tmux_pilot.worktree._run_git", fake_run_git)
        monkeypatch.setattr("tmux_pilot.worktree.list_sessions", lambda: [])

        result = scan_worktrees(str(tmp_path), repo="repoA")
        assert len(result) == 1
        assert result[0].repo_name == "repoA"

    def test_orphan_only_filter(self, tmp_path, monkeypatch):
        wt_dir = tmp_path / "feat"
        wt_dir.mkdir()
        (wt_dir / ".git").write_text("gitdir: /repos/r/.git/worktrees/feat\n")

        import subprocess as _sp
        from tmux_pilot.core import SessionInfo

        dt = datetime.now(timezone.utc).isoformat()

        def fake_run_git(args, *, cwd=None, timeout=10):
            if "log" in args and "--format=%D%n%aI" in args:
                return _sp.CompletedProcess(args, 0, stdout=f"HEAD -> feat\n{dt}\n", stderr="")
            if "status" in args:
                return _sp.CompletedProcess(args, 0, stdout="", stderr="")
            return _sp.CompletedProcess(args, 1, stdout="", stderr="")

        # Session matches the worktree path
        fake_session = SessionInfo(
            name="feat",
            working_dir=str(wt_dir), process="zsh", pid="1234",
        )
        monkeypatch.setattr("tmux_pilot.worktree._run_git", fake_run_git)
        monkeypatch.setattr("tmux_pilot.worktree.list_sessions", lambda: [fake_session])

        # With orphan_only, the session-linked worktree should be excluded
        result = scan_worktrees(str(tmp_path), orphan_only=True)
        assert len(result) == 0

        # Without filter it should appear
        result = scan_worktrees(str(tmp_path))
        assert len(result) == 1

    def test_stale_days_filter(self, tmp_path, monkeypatch):
        wt_dir = tmp_path / "old-branch"
        wt_dir.mkdir()
        (wt_dir / ".git").write_text("gitdir: /repos/r/.git/worktrees/old-branch\n")

        import subprocess as _sp

        old_date = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()

        def fake_run_git(args, *, cwd=None, timeout=10):
            if "log" in args and "--format=%D%n%aI" in args:
                return _sp.CompletedProcess(args, 0, stdout=f"HEAD -> old-branch\n{old_date}\n", stderr="")
            if "status" in args:
                return _sp.CompletedProcess(args, 0, stdout="", stderr="")
            return _sp.CompletedProcess(args, 1, stdout="", stderr="")

        monkeypatch.setattr("tmux_pilot.worktree._run_git", fake_run_git)
        monkeypatch.setattr("tmux_pilot.worktree.list_sessions", lambda: [])

        # stale_days=30 means only show worktrees older than 30 days
        result = scan_worktrees(str(tmp_path), stale_days=30)
        assert len(result) == 0

        # stale_days=10 means show worktrees older than 10 days (20 > 10)
        result = scan_worktrees(str(tmp_path), stale_days=10)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# worktree_summary
# ---------------------------------------------------------------------------


class TestWorktreeSummary:
    def test_empty_list(self):
        s = worktree_summary([])
        assert s == {"total": 0, "by_repo": {}, "by_status": {"orphan": 0, "stale": 0, "active": 0, "merged": 0}}

    def test_counts_by_repo(self):
        wts = [
            _make_wt(repo_name="alpha"),
            _make_wt(repo_name="alpha"),
            _make_wt(repo_name="beta"),
        ]
        s = worktree_summary(wts)
        assert s["total"] == 3
        assert s["by_repo"] == {"alpha": 2, "beta": 1}

    def test_status_categories(self):
        wts = [
            _make_wt(has_session=True, age_days=1, is_merged=False),   # active
            _make_wt(has_session=False, age_days=1, is_merged=False),  # orphan
            _make_wt(has_session=True, age_days=10, is_merged=False),  # stale
            _make_wt(has_session=True, age_days=1, is_merged=True),    # merged
        ]
        s = worktree_summary(wts)
        assert s["by_status"]["active"] == 1
        assert s["by_status"]["orphan"] == 1
        assert s["by_status"]["stale"] == 1
        assert s["by_status"]["merged"] == 1

    def test_merged_takes_priority(self):
        # A merged worktree that is also orphan should be counted as merged
        wt = _make_wt(has_session=False, is_merged=True, age_days=20)
        s = worktree_summary([wt])
        assert s["by_status"]["merged"] == 1
        assert s["by_status"]["orphan"] == 0


# ---------------------------------------------------------------------------
# clean_worktrees
# ---------------------------------------------------------------------------


class TestCleanWorktrees:
    def test_dry_run_returns_actions_without_removal(self):
        wts = [
            _make_wt(path="/tmp/wt/merged-one", branch="feat-1", is_merged=True),
            _make_wt(path="/tmp/wt/orphan-stale", branch="feat-2", has_session=False, age_days=10),
        ]
        actions = clean_worktrees(wts, dry_run=True)
        assert len(actions) == 2
        assert actions[0]["reason"] == "merged"
        assert actions[0]["dry_run"] is True
        assert actions[0]["removed"] is False
        assert actions[1]["reason"] == "orphan+stale"

    def test_skips_active_worktrees(self):
        wts = [
            _make_wt(has_session=True, age_days=1, is_merged=False),
        ]
        actions = clean_worktrees(wts, dry_run=True)
        assert actions == []

    def test_skips_orphan_but_not_stale(self):
        wts = [
            _make_wt(has_session=False, age_days=3, is_merged=False),
        ]
        actions = clean_worktrees(wts, dry_run=True)
        assert actions == []

    def test_includes_orphan_and_stale(self):
        wts = [
            _make_wt(has_session=False, age_days=10, is_merged=False),
        ]
        actions = clean_worktrees(wts, dry_run=True)
        assert len(actions) == 1
        assert actions[0]["reason"] == "orphan+stale"

    def test_actual_removal_calls_core(self, monkeypatch):
        removed_paths = []
        deleted_branches = []

        monkeypatch.setattr("tmux_pilot.worktree.remove_worktree", lambda p: (removed_paths.append(p), True)[1])
        monkeypatch.setattr("tmux_pilot.worktree.delete_branch", lambda p, b: (deleted_branches.append((p, b)), True)[1])

        wts = [_make_wt(path="/tmp/wt/x", branch="feat-x", is_merged=True)]
        actions = clean_worktrees(wts, dry_run=False)
        assert actions[0]["removed"] is True
        assert actions[0]["branch_deleted"] is True
        assert removed_paths == ["/tmp/wt/x"]
        assert deleted_branches == [("/tmp/wt/x", "feat-x")]

    def test_does_not_delete_main_branch(self, monkeypatch):
        deleted_branches = []
        monkeypatch.setattr("tmux_pilot.worktree.remove_worktree", lambda p: True)
        monkeypatch.setattr("tmux_pilot.worktree.delete_branch", lambda p, b: (deleted_branches.append(b), True)[1])

        wts = [_make_wt(path="/tmp/wt/y", branch="main", is_merged=True)]
        actions = clean_worktrees(wts, dry_run=False)
        assert actions[0]["removed"] is True
        assert actions[0]["branch_deleted"] is False
        assert deleted_branches == []


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCLIWorktree:
    def test_wt_ls_json(self, monkeypatch, capsys):
        fake_wt = _make_wt(path="/tmp/wt/test", branch="test-br")
        monkeypatch.setattr("tmux_pilot.worktree.scan_worktrees", lambda **kw: [fake_wt])

        try:
            cli_main(["wt", "ls", "--json"])
        except SystemExit as e:
            if e.code not in (None, 0):
                pytest.fail(f"CLI exited with code {e.code}")

        out = capsys.readouterr().out
        assert "test-br" in out

    def test_wt_ls_json_output(self, monkeypatch, capsys):
        fake_wt = _make_wt(path="/tmp/wt/test", branch="test-br")
        monkeypatch.setattr("tmux_pilot.worktree.scan_worktrees", lambda **kw: [fake_wt])

        try:
            cli_main(["wt", "ls", "--json"])
        except SystemExit:
            pass

        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, list)
        assert data[0]["branch"] == "test-br"

    def test_wt_status_json(self, monkeypatch, capsys):
        wts = [_make_wt(repo_name="r1"), _make_wt(repo_name="r2", has_session=False)]
        monkeypatch.setattr("tmux_pilot.worktree.scan_worktrees", lambda **kw: wts)

        try:
            cli_main(["wt", "status", "--json"])
        except SystemExit:
            pass

        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["total"] == 2
        assert "by_repo" in data
        assert "by_status" in data
