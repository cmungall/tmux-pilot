"""Tests for tmux-pilot core functionality.

These tests create real tmux sessions, so they require tmux to be installed.
Sessions are cleaned up in teardown.
"""

from __future__ import annotations

import json
import subprocess
import time
import pytest

from tmux_pilot import core
from tmux_pilot.cli import main as cli_main
from tmux_pilot.display import format_session_table, parse_cols


TEST_SESSION = "_tp_test_session"


def _cleanup_session(name: str = TEST_SESSION) -> None:
    """Kill test session if it exists."""
    subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)


@pytest.fixture(autouse=True)
def cleanup():
    """Ensure test sessions are cleaned up."""
    _cleanup_session()
    yield
    _cleanup_session()


def _has_tmux() -> bool:
    return subprocess.run(["which", "tmux"], capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(not _has_tmux(), reason="tmux not installed")


class TestSessionLifecycle:
    """Test creating, listing, and killing sessions."""

    def test_new_and_exists(self):
        assert not core.session_exists(TEST_SESSION)
        core.new_session(TEST_SESSION, desc="test session")
        assert core.session_exists(TEST_SESSION)

    def test_new_with_directory(self, tmp_path):
        core.new_session(TEST_SESSION, directory=str(tmp_path), desc="dir test")
        assert core.session_exists(TEST_SESSION)
        info = core.get_session_status(TEST_SESSION)
        assert str(tmp_path) in info["working_dir"]

    def test_kill_session(self):
        core.new_session(TEST_SESSION)
        assert core.session_exists(TEST_SESSION)
        core.kill_session(TEST_SESSION)
        assert not core.session_exists(TEST_SESSION)

    def test_list_sessions(self):
        core.new_session(TEST_SESSION, desc="list test")
        sessions = core.list_sessions()
        names = [s.name for s in sessions]
        assert TEST_SESSION in names

    def test_list_sessions_metadata(self):
        core.new_session(TEST_SESSION, desc="meta test")
        sessions = core.list_sessions()
        s = next(s for s in sessions if s.name == TEST_SESSION)
        assert s.desc == "meta test"


class TestMetadata:
    """Test get/set metadata."""

    def test_set_and_get(self):
        core.new_session(TEST_SESSION)
        core.set_metadata(TEST_SESSION, "status", "running")
        assert core.get_metadata(TEST_SESSION, "status") == "running"

    def test_get_missing_key(self):
        core.new_session(TEST_SESSION)
        assert core.get_metadata(TEST_SESSION, "nonexistent") == ""

    def test_overwrite(self):
        core.new_session(TEST_SESSION)
        core.set_metadata(TEST_SESSION, "status", "running")
        core.set_metadata(TEST_SESSION, "status", "done")
        assert core.get_metadata(TEST_SESSION, "status") == "done"


class TestPeekAndSend:
    """Test peeking at scrollback and sending keys."""

    def test_peek_empty(self):
        core.new_session(TEST_SESSION)
        output = core.peek_session(TEST_SESSION, lines=10)
        # Should return something (possibly empty or with prompt)
        assert isinstance(output, str)

    def test_send_and_peek(self):
        core.new_session(TEST_SESSION)
        core.send_keys(TEST_SESSION, "echo TMUX_PILOT_TEST_MARKER")
        time.sleep(0.5)  # let the command execute
        output = core.peek_session(TEST_SESSION, lines=20)
        assert "TMUX_PILOT_TEST_MARKER" in output


class TestResolveSession:
    """Test substring matching for jump."""

    def test_exact_match(self):
        core.new_session(TEST_SESSION)
        assert core._resolve_session(TEST_SESSION) == TEST_SESSION

    def test_substring_match(self):
        core.new_session(TEST_SESSION)
        # "_tp_test" is a substring of "_tp_test_session"
        assert core._resolve_session("_tp_test") == TEST_SESSION

    def test_no_match(self):
        core.new_session(TEST_SESSION)
        with pytest.raises(RuntimeError, match="No session matching"):
            core._resolve_session("_xyzzy_nonexistent_99")

    def test_multiple_matches(self):
        core.new_session(TEST_SESSION)
        other = TEST_SESSION + "_2"
        try:
            core.new_session(other)
            with pytest.raises(RuntimeError, match="matches multiple"):
                core._resolve_session("_tp_test")
        finally:
            _cleanup_session(other)


class TestStatus:
    """Test detailed status."""

    def test_status(self):
        core.new_session(TEST_SESSION, desc="status test")
        core.set_metadata(TEST_SESSION, "status", "active")
        info = core.get_session_status(TEST_SESSION)
        assert info["name"] == TEST_SESSION
        assert info["metadata"]["status"] == "active"
        assert info["metadata"]["desc"] == "status test"
        assert "process" in info

    def test_status_nonexistent(self):
        with pytest.raises(RuntimeError, match="not found"):
            core.get_session_status("_tp_nonexistent_xyz")


class TestFiltering:
    """Test list_sessions filtering."""

    def test_filter_by_status(self):
        core.new_session(TEST_SESSION, desc="filter test")
        core.set_metadata(TEST_SESSION, "status", "active")
        sessions = core.list_sessions(status="active")
        names = [s.name for s in sessions]
        assert TEST_SESSION in names

        sessions = core.list_sessions(status="done")
        names = [s.name for s in sessions]
        assert TEST_SESSION not in names

    def test_filter_by_process(self):
        core.new_session(TEST_SESSION)
        sessions = core.list_sessions()
        test_session = next(s for s in sessions if s.name == TEST_SESSION)
        # Filter by whatever process the test session is running
        sessions = core.list_sessions(process=test_session.process)
        names = [s.name for s in sessions]
        assert TEST_SESSION in names

    def test_filter_by_repo(self):
        core.new_session(TEST_SESSION, directory="/tmp")
        sessions = core.list_sessions(repo="tmp")
        names = [s.name for s in sessions]
        # Should match either repo metadata or session name
        assert TEST_SESSION in names or any("tmp" in n for n in names)


class TestClean:
    """Test bulk cleanup of sessions."""

    def test_clean_dry_run(self):
        core.new_session(TEST_SESSION, desc="clean test")
        core.set_metadata(TEST_SESSION, "status", "done")
        actions = core.clean_sessions(dry_run=True)
        names = [a["session"] for a in actions]
        assert TEST_SESSION in names
        # Session should still exist after dry run
        assert core.session_exists(TEST_SESSION)

    def test_clean_by_status(self):
        core.new_session(TEST_SESSION, desc="clean test")
        core.set_metadata(TEST_SESSION, "status", "done")
        actions = core.clean_sessions()
        names = [a["session"] for a in actions]
        assert TEST_SESSION in names
        assert not core.session_exists(TEST_SESSION)

    def test_clean_skips_active(self):
        core.new_session(TEST_SESSION, desc="active test")
        core.set_metadata(TEST_SESSION, "status", "active")
        actions = core.clean_sessions()
        names = [a["session"] for a in actions]
        assert TEST_SESSION not in names
        assert core.session_exists(TEST_SESSION)

    def test_clean_specific_session(self):
        core.new_session(TEST_SESSION, desc="target test")
        actions = core.clean_sessions(target=TEST_SESSION)
        assert len(actions) == 1
        assert actions[0]["session"] == TEST_SESSION
        assert not core.session_exists(TEST_SESSION)

    def test_clean_custom_status(self):
        core.new_session(TEST_SESSION, desc="custom test")
        core.set_metadata(TEST_SESSION, "status", "archived")
        actions = core.clean_sessions(status_filter="archived")
        names = [a["session"] for a in actions]
        assert TEST_SESSION in names
        assert not core.session_exists(TEST_SESSION)


class TestSessionInfoDict:
    """Test SessionInfo.to_dict serialization."""

    def test_to_dict(self):
        s = core.SessionInfo(
            name="test",
            process="claude-code",
            working_dir="/tmp",
            metadata={"status": "active", "desc": "hello"},
        )
        d = s.to_dict()
        assert d["name"] == "test"
        assert d["process"] == "claude-code"
        assert d["metadata"]["status"] == "active"
        # Should be JSON-serializable
        json.dumps(d)


class TestDisplay:
    """Test display formatting."""

    def test_format_empty(self):
        result = format_session_table([])
        assert "No tmux sessions" in result

    def test_format_sessions(self):
        sessions = [
            core.SessionInfo(
                name="test1",
                process="claude-code",
                working_dir="/tmp/test",
                metadata={"status": "running", "desc": "my test"},
            ),
        ]
        result = format_session_table(sessions)
        assert "test1" in result
        assert "claude-code" in result
        assert "running" in result

    def test_cols_mnemonics(self):
        sessions = [
            core.SessionInfo(name="s1", process="python", metadata={"status": "active"}),
        ]
        result = format_session_table(sessions, cols="NSP")
        assert "NAME" in result
        assert "STATUS" in result
        assert "PROCESS" in result
        assert "DESC" not in result

    def test_cols_long_names(self):
        sessions = [
            core.SessionInfo(name="s1", metadata={"branch": "feat/x"}),
        ]
        result = format_session_table(sessions, cols="NAME,BRANCH")
        assert "NAME" in result
        assert "BRANCH" in result
        assert "feat/x" in result

    def test_cols_all(self):
        sessions = [
            core.SessionInfo(
                name="s1", process="zsh", working_dir="/tmp",
                metadata={"status": "a", "desc": "b", "repo": "/r", "task": "t", "branch": "br"},
            ),
        ]
        result = format_session_table(sessions, cols="NSPDWRTB")
        for header in ("NAME", "STATUS", "PROCESS", "DESC", "DIR", "REPO", "TASK", "BRANCH"):
            assert header in result

    def test_parse_cols_invalid_mnemonic(self):
        with pytest.raises(ValueError, match="Unknown column mnemonic"):
            parse_cols("NXP")

    def test_parse_cols_invalid_name(self):
        with pytest.raises(ValueError, match="Unknown column"):
            parse_cols("NAME,BOGUS")


class TestCLI:
    """Test CLI entry point."""

    def test_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "tmux-pilot" in captured.out

    def test_version(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["--version"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "0.2.0" in captured.out

    def test_ls(self, capsys):
        cli_main(["ls"])
        captured = capsys.readouterr()
        assert isinstance(captured.out, str)

    def test_ls_json(self, capsys):
        core.new_session(TEST_SESSION, desc="json test")
        cli_main(["ls", "--json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
        names = [s["name"] for s in data]
        assert TEST_SESSION in names

    def test_ls_filter(self, capsys):
        core.new_session(TEST_SESSION, desc="filter test")
        core.set_metadata(TEST_SESSION, "status", "active")
        cli_main(["ls", "--status", "active"])
        captured = capsys.readouterr()
        assert TEST_SESSION in captured.out

    def test_ls_json_with_filter(self, capsys):
        core.new_session(TEST_SESSION, desc="combo test")
        core.set_metadata(TEST_SESSION, "status", "active")
        cli_main(["ls", "--json", "--status", "active"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        names = [s["name"] for s in data]
        assert TEST_SESSION in names
