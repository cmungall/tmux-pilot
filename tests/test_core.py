"""Unit tests for tmux-pilot core and CLI behavior."""

from __future__ import annotations

import json
import re
import subprocess

import pytest

from tmux_pilot import agent_sessions, core
from tmux_pilot.cli import main as cli_main
from tmux_pilot.display import format_session_table, parse_cols


TEST_SESSION = "_tp_test_session"


class FakeTmux:
    """Minimal tmux stub that exercises core logic without a real server."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, object]] = {}
        self.cwd = "/tmp"
        self.next_pid = 1000
        self.switched_to: str | None = None
        self.attached_to: str | None = None
        self.send_key_calls: list[tuple[str, bool, list[str]]] = []

    def run(
        self,
        args: list[str],
        *,
        check: bool = True,
        capture: bool = True,
        timeout: int = 5,
    ) -> subprocess.CompletedProcess[str]:
        del capture, timeout

        if not args or args[0] != "tmux":
            return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="unsupported")

        command = args[1]
        if command == "new-session":
            name = args[args.index("-s") + 1]
            directory = self.cwd
            if "-c" in args:
                directory = args[args.index("-c") + 1]
            self.sessions[name] = {
                "command": "zsh",
                "path": directory,
                "pid": str(self.next_pid),
                "metadata": {},
                "scrollback": "",
                "input_buffer": "",
            }
            self.next_pid += 1
            return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

        if command == "has-session":
            name = args[args.index("-t") + 1]
            return self._completed(args, name in self.sessions, check=check)

        if command == "kill-session":
            name = args[args.index("-t") + 1]
            exists = name in self.sessions
            if exists:
                del self.sessions[name]
            return self._completed(args, exists, check=check)

        if command == "list-sessions":
            if "-F" not in args:
                stdout = "\n".join(self.sessions)
                return subprocess.CompletedProcess(args, returncode=0, stdout=stdout, stderr="")

            fmt = args[args.index("-F") + 1]
            lines = [
                self._render_format(fmt, name, session)
                for name, session in sorted(self.sessions.items())
            ]
            return subprocess.CompletedProcess(
                args,
                returncode=0,
                stdout="\n".join(lines),
                stderr="",
            )

        if command == "display-message":
            name = args[args.index("-t") + 1]
            fmt = args[-1]
            session = self.sessions.get(name)
            if session is None:
                return self._completed(args, False, check=check)
            stdout = self._render_format(fmt, name, session)
            return subprocess.CompletedProcess(args, returncode=0, stdout=stdout, stderr="")

        if command == "set-option":
            name = args[args.index("-t") + 1]
            key = args[-2].removeprefix("@")
            value = args[-1]
            self.sessions[name]["metadata"][key] = value
            return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

        if command == "capture-pane":
            name = args[args.index("-t") + 1]
            session = self.sessions[name]
            return subprocess.CompletedProcess(
                args,
                returncode=0,
                stdout=str(session["scrollback"]),
                stderr="",
            )

        if command == "send-keys":
            name = args[args.index("-t") + 1]
            keys = args[args.index("-t") + 2 :]
            literal = False
            if keys and keys[0] == "-l":
                literal = True
                keys = keys[1:]
            self.send_key_calls.append((name, literal, list(keys)))

            session = self.sessions[name]
            if literal:
                session["input_buffer"] = str(session["input_buffer"]) + "".join(keys)
                return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

            for key in keys:
                if key == "Enter":
                    text = str(session["input_buffer"])
                    scrollback = f"$ {text}\n"
                    if text.startswith("echo "):
                        scrollback += text[5:] + "\n"
                    session["scrollback"] = str(session["scrollback"]) + scrollback
                    session["input_buffer"] = ""
                else:
                    session["input_buffer"] = str(session["input_buffer"]) + key
            return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

        if command == "list-panes":
            name = args[args.index("-t") + 1]
            fmt = args[args.index("-F") + 1]
            session = self.sessions[name]
            stdout = self._render_format(fmt, name, session)
            return subprocess.CompletedProcess(args, returncode=0, stdout=stdout, stderr="")

        if command == "switch-client":
            self.switched_to = args[args.index("-t") + 1]
            return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

        if command == "attach-session":
            self.attached_to = args[args.index("-t") + 1]
            return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="unsupported")

    def _completed(
        self,
        args: list[str],
        ok: bool,
        *,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        if ok:
            return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")
        if check:
            raise subprocess.CalledProcessError(1, args, "", "")
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="")

    def _render_format(self, fmt: str, name: str, session: dict[str, object]) -> str:
        rendered = fmt
        replacements = {
            "#{session_name}": name,
            "#{pane_current_command}": str(session["command"]),
            "#{pane_current_path}": str(session["path"]),
            "#{pane_pid}": str(session["pid"]),
        }
        for token, value in replacements.items():
            rendered = rendered.replace(token, value)
        for key in core.METADATA_KEYS:
            rendered = rendered.replace(f"#{{@{key}}}", str(session["metadata"].get(key, "")))
        return re.sub(r"#\{@[^}]+\}", "", rendered)


@pytest.fixture
def fake_tmux(monkeypatch: pytest.MonkeyPatch) -> FakeTmux:
    fake = FakeTmux()
    monkeypatch.setattr(core, "_run", fake.run)
    return fake


class TestSessionLifecycle:
    def test_new_and_exists(self, fake_tmux: FakeTmux):
        assert not core.session_exists(TEST_SESSION)
        core.new_session(TEST_SESSION, desc="test session")
        assert core.session_exists(TEST_SESSION)
        assert fake_tmux.sessions[TEST_SESSION]["metadata"]["desc"] == "test session"

    def test_new_with_directory(self, fake_tmux: FakeTmux, tmp_path):
        core.new_session(TEST_SESSION, directory=str(tmp_path), desc="dir test")
        info = core.get_session_status(TEST_SESSION)
        assert info["working_dir"] == str(tmp_path)
        assert fake_tmux.sessions[TEST_SESSION]["metadata"]["repo"] == str(tmp_path)

    def test_kill_session(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION)
        core.kill_session(TEST_SESSION)
        assert TEST_SESSION not in fake_tmux.sessions

    def test_list_sessions(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION, desc="list test")
        sessions = core.list_sessions()
        assert [s.name for s in sessions] == [TEST_SESSION]

    def test_list_sessions_metadata(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION, desc="meta test")
        session = core.list_sessions()[0]
        assert session.desc == "meta test"


class TestMetadata:
    def test_set_and_get(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION)
        core.set_metadata(TEST_SESSION, "status", "running")
        assert core.get_metadata(TEST_SESSION, "status") == "running"

    def test_get_missing_key(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION)
        assert core.get_metadata(TEST_SESSION, "nonexistent") == ""

    def test_overwrite(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION)
        core.set_metadata(TEST_SESSION, "status", "running")
        core.set_metadata(TEST_SESSION, "status", "done")
        assert core.get_metadata(TEST_SESSION, "status") == "done"


class TestPeekAndSend:
    def test_peek_empty(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION)
        assert core.peek_session(TEST_SESSION, lines=10) == ""

    def test_send_and_peek(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION)
        core.send_keys(TEST_SESSION, "echo TMUX_PILOT_TEST_MARKER")
        output = core.peek_session(TEST_SESSION, lines=20)
        assert "TMUX_PILOT_TEST_MARKER" in output

    def test_send_uses_literal_text_then_enter(self, fake_tmux: FakeTmux, monkeypatch: pytest.MonkeyPatch):
        sleeps: list[float] = []
        monkeypatch.setattr(core.time, "sleep", lambda seconds: sleeps.append(seconds))
        core.new_session(TEST_SESSION)
        core.send_keys(TEST_SESSION, "echo hello")
        assert fake_tmux.send_key_calls == [
            (TEST_SESSION, True, ["echo hello"]),
            (TEST_SESSION, False, ["Enter"]),
        ]
        assert sleeps == [core._SEND_KEYS_SETTLE_DELAY]

    def test_send_empty_text_sends_enter_only(self, fake_tmux: FakeTmux, monkeypatch: pytest.MonkeyPatch):
        sleeps: list[float] = []
        monkeypatch.setattr(core.time, "sleep", lambda seconds: sleeps.append(seconds))
        core.new_session(TEST_SESSION)
        core.send_keys(TEST_SESSION, "")
        assert fake_tmux.send_key_calls == [
            (TEST_SESSION, False, ["Enter"]),
        ]
        assert sleeps == []

    def test_send_text_waits_before_sending(self, fake_tmux: FakeTmux, monkeypatch: pytest.MonkeyPatch):
        core.new_session(TEST_SESSION)
        calls: list[tuple[str, float, float]] = []

        def wait_until_session_ready(name: str, *, timeout: float, interval: float):
            calls.append((name, timeout, interval))
            return {"type": "codex", "state": "completed", "ready": True}

        monkeypatch.setattr(core, "wait_until_session_ready", wait_until_session_ready)

        agent = core.send_text(TEST_SESSION, "echo waited", wait=True, timeout=12.5)

        assert calls == [(TEST_SESSION, 12.5, 0.25)]
        assert agent == {"type": "codex", "state": "completed", "ready": True}
        assert fake_tmux.send_key_calls == [
            (TEST_SESSION, True, ["echo waited"]),
            (TEST_SESSION, False, ["Enter"]),
        ]


class TestWaitForReady:
    def test_wait_until_session_ready_returns_when_agent_ready(
        self,
        fake_tmux: FakeTmux,
        monkeypatch: pytest.MonkeyPatch,
    ):
        core.new_session(TEST_SESSION, directory="/tmp/example")
        fake_tmux.sessions[TEST_SESSION]["command"] = "codex"
        monkeypatch.setattr(core, "peek_session", lambda name, lines=30: "OpenAI Codex")
        monkeypatch.setattr(agent_sessions, "find_transcript_for_cwd", lambda agent_type, cwd: None)

        states = iter(
            [
                {"type": "codex", "state": "running", "ready": False},
                {"type": "codex", "state": "completed", "ready": True},
            ]
        )
        monkeypatch.setattr(core, "_get_agent_state", lambda *args, **kwargs: next(states))

        sleeps: list[float] = []
        monkeypatch.setattr(core.time, "sleep", lambda seconds: sleeps.append(seconds))

        agent = core.wait_until_session_ready(TEST_SESSION, timeout=1.0, interval=0.1)

        assert agent == {"type": "codex", "state": "completed", "ready": True}
        assert sleeps == [0.1]

    def test_wait_until_session_ready_times_out(
        self,
        fake_tmux: FakeTmux,
        monkeypatch: pytest.MonkeyPatch,
    ):
        core.new_session(TEST_SESSION, directory="/tmp/example")
        fake_tmux.sessions[TEST_SESSION]["command"] = "codex"
        monkeypatch.setattr(core, "peek_session", lambda name, lines=30: "OpenAI Codex")
        monkeypatch.setattr(agent_sessions, "find_transcript_for_cwd", lambda agent_type, cwd: None)
        monkeypatch.setattr(
            core,
            "_get_agent_state",
            lambda *args, **kwargs: {"type": "codex", "state": "running", "ready": False},
        )

        monotonic_values = iter([0.0, 0.2, 0.6])
        monkeypatch.setattr(core.time, "monotonic", lambda: next(monotonic_values))
        monkeypatch.setattr(core.time, "sleep", lambda seconds: None)

        with pytest.raises(RuntimeError, match="Timed out waiting for session '_tp_test_session'"):
            core.wait_until_session_ready(TEST_SESSION, timeout=0.5, interval=0.1)


class TestResolveSession:
    def test_exact_match(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION)
        assert core._resolve_session(TEST_SESSION) == TEST_SESSION

    def test_substring_match(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION)
        assert core._resolve_session("_tp_test") == TEST_SESSION

    def test_no_match(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION)
        with pytest.raises(RuntimeError, match="No session matching"):
            core._resolve_session("_xyzzy_nonexistent_99")

    def test_multiple_matches(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION)
        core.new_session(TEST_SESSION + "_2")
        with pytest.raises(RuntimeError, match="matches multiple"):
            core._resolve_session("_tp_test")


class TestStatus:
    def test_status(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION, desc="status test")
        core.set_metadata(TEST_SESSION, "status", "active")
        info = core.get_session_status(TEST_SESSION)
        assert info["name"] == TEST_SESSION
        assert info["metadata"]["status"] == "active"
        assert info["metadata"]["desc"] == "status test"
        assert info["process"] == "zsh"

    def test_status_nonexistent(self, fake_tmux: FakeTmux):
        with pytest.raises(RuntimeError, match="not found"):
            core.get_session_status("_tp_nonexistent_xyz")


class TestFiltering:
    def test_filter_by_status(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION, desc="filter test")
        core.set_metadata(TEST_SESSION, "status", "active")
        assert [s.name for s in core.list_sessions(status="active")] == [TEST_SESSION]
        assert core.list_sessions(status="done") == []

    def test_filter_by_process(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION)
        assert [s.name for s in core.list_sessions(process="zsh")] == [TEST_SESSION]

    def test_filter_by_repo(self, fake_tmux: FakeTmux, tmp_path):
        core.new_session(TEST_SESSION, directory=str(tmp_path))
        assert [s.name for s in core.list_sessions(repo=tmp_path.name)] == [TEST_SESSION]


class TestClean:
    def test_clean_dry_run(self, fake_tmux: FakeTmux, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(core, "_is_git_worktree", lambda path: path == "/tmp/worktree")
        core.new_session(TEST_SESSION, desc="clean test")
        fake_tmux.sessions[TEST_SESSION]["path"] = "/tmp/worktree"
        core.set_metadata(TEST_SESSION, "status", "done")
        actions = core.clean_sessions(dry_run=True)
        assert actions == [
            {
                "session": TEST_SESSION,
                "killed": False,
                "worktree_removed": False,
                "branch_deleted": False,
                "dry_run": True,
                "would_kill": True,
                "would_remove_worktree": True,
            }
        ]
        assert core.session_exists(TEST_SESSION)

    def test_clean_by_status(self, fake_tmux: FakeTmux, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(core, "_is_git_worktree", lambda path: False)
        core.new_session(TEST_SESSION, desc="clean test")
        core.set_metadata(TEST_SESSION, "status", "done")
        actions = core.clean_sessions()
        assert actions[0]["session"] == TEST_SESSION
        assert not core.session_exists(TEST_SESSION)

    def test_clean_skips_active(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION, desc="active test")
        core.set_metadata(TEST_SESSION, "status", "active")
        assert core.clean_sessions() == []
        assert core.session_exists(TEST_SESSION)

    def test_clean_specific_session(self, fake_tmux: FakeTmux, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(core, "_is_git_worktree", lambda path: False)
        core.new_session(TEST_SESSION, desc="target test")
        actions = core.clean_sessions(target=TEST_SESSION)
        assert actions[0]["session"] == TEST_SESSION
        assert not core.session_exists(TEST_SESSION)

    def test_clean_custom_status(self, fake_tmux: FakeTmux, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(core, "_is_git_worktree", lambda path: False)
        core.new_session(TEST_SESSION, desc="custom test")
        core.set_metadata(TEST_SESSION, "status", "archived")
        actions = core.clean_sessions(status_filter="archived")
        assert actions[0]["session"] == TEST_SESSION
        assert not core.session_exists(TEST_SESSION)


class TestSessionInfoDict:
    def test_to_dict(self):
        session = core.SessionInfo(
            name="test",
            process="claude-code",
            working_dir="/tmp",
            metadata={"status": "active", "desc": "hello"},
        )
        serialized = session.to_dict()
        assert serialized["name"] == "test"
        assert serialized["process"] == "claude-code"
        assert serialized["metadata"]["status"] == "active"
        json.dumps(serialized)


class TestDisplay:
    def test_format_empty(self):
        assert "No tmux sessions" in format_session_table([])

    def test_format_sessions(self):
        result = format_session_table(
            [
                core.SessionInfo(
                    name="test1",
                    process="claude-code",
                    working_dir="/tmp/test",
                    metadata={"status": "running", "desc": "my test"},
                )
            ]
        )
        assert "test1" in result
        assert "claude-code" in result
        assert "running" in result

    def test_cols_mnemonics(self):
        result = format_session_table(
            [core.SessionInfo(name="s1", process="python", metadata={"status": "active"})],
            cols="NSP",
        )
        assert "NAME" in result
        assert "STATUS" in result
        assert "PROCESS" in result
        assert "DESC" not in result

    def test_cols_long_names(self):
        result = format_session_table(
            [core.SessionInfo(name="s1", metadata={"branch": "feat/x"})],
            cols="NAME,BRANCH",
        )
        assert "NAME" in result
        assert "BRANCH" in result
        assert "feat/x" in result

    def test_cols_all_mnemonics(self):
        result = format_session_table(
            [
                core.SessionInfo(
                    name="s1",
                    process="zsh",
                    working_dir="/tmp",
                    metadata={
                        "status": "a",
                        "desc": "b",
                        "repo": "/r",
                        "task": "t",
                        "branch": "br",
                    },
                )
            ],
            cols="NSPDWRTB",
        )
        for header in ("NAME", "STATUS", "PROCESS", "DESC", "DIR", "REPO", "TASK", "BRANCH"):
            assert header in result

    def test_cols_all_keyword(self):
        result = format_session_table(
            [
                core.SessionInfo(
                    name="s1",
                    process="zsh",
                    working_dir="/tmp",
                    metadata={
                        "status": "a",
                        "desc": "b",
                        "repo": "/r",
                        "task": "t",
                        "branch": "br",
                    },
                )
            ],
            cols="ALL",
        )
        for header in ("NAME", "STATUS", "PROCESS", "DESC", "DIR", "REPO", "TASK", "BRANCH"):
            assert header in result

    def test_parse_cols_invalid_mnemonic(self):
        with pytest.raises(ValueError, match="Unknown column mnemonic"):
            parse_cols("NZP")

    def test_parse_cols_invalid_name(self):
        with pytest.raises(ValueError, match="Unknown column"):
            parse_cols("NAME,BOGUS")


class TestCLI:
    def test_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["--help"])
        assert exc_info.value.code == 0
        assert "tmux-pilot" in capsys.readouterr().out

    def test_version(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["--version"])
        assert exc_info.value.code == 0
        assert "0.3.0" in capsys.readouterr().out

    def test_ls(self, fake_tmux: FakeTmux, capsys):
        cli_main(["ls"])
        assert isinstance(capsys.readouterr().out, str)

    def test_ls_json(self, fake_tmux: FakeTmux, capsys):
        core.new_session(TEST_SESSION, desc="json test")
        cli_main(["ls", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert [session["name"] for session in data] == [TEST_SESSION]

    def test_ls_filter(self, fake_tmux: FakeTmux, capsys):
        core.new_session(TEST_SESSION, desc="filter test")
        core.set_metadata(TEST_SESSION, "status", "active")
        cli_main(["ls", "--status", "active"])
        assert TEST_SESSION in capsys.readouterr().out

    def test_ls_json_with_filter(self, fake_tmux: FakeTmux, capsys):
        core.new_session(TEST_SESSION, desc="combo test")
        core.set_metadata(TEST_SESSION, "status", "active")
        cli_main(["ls", "--json", "--status", "active"])
        data = json.loads(capsys.readouterr().out)
        assert [session["name"] for session in data] == [TEST_SESSION]

    def test_send_with_wait(self, monkeypatch: pytest.MonkeyPatch):
        calls: list[tuple[str, str, bool, float]] = []
        monkeypatch.setattr(core, "session_exists", lambda name: True)

        def send_text(name: str, text: str, *, wait: bool, timeout: float, interval: float = 0.25):
            calls.append((name, text, wait, timeout))
            return {"type": "codex", "state": "completed", "ready": True}

        monkeypatch.setattr(core, "send_text", send_text)

        cli_main(["send", "--wait", "--timeout", "12.0", TEST_SESSION, "hello"])

        assert calls == [(TEST_SESSION, "hello", True, 12.0)]

    def test_send_wait_reports_errors(self, monkeypatch: pytest.MonkeyPatch, capsys):
        monkeypatch.setattr(core, "session_exists", lambda name: True)
        monkeypatch.setattr(core, "send_text", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

        with pytest.raises(SystemExit) as exc_info:
            cli_main(["send", "--wait", TEST_SESSION, "hello"])

        assert exc_info.value.code == 1
        assert "boom" in capsys.readouterr().err
