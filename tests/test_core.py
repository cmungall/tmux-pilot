"""Unit tests for tmux-pilot core and CLI behavior."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tmux_pilot import agent_sessions, core, reaper
from tmux_pilot.cli import main as cli_main
from tmux_pilot.display import format_session_table, format_status, parse_cols


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
        self.ignore_cd = False
        self.path_after_commands: dict[str, str] = {}

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
                    parts = shlex.split(text) if text else []
                    if parts and parts[0] == "cd" and len(parts) > 1 and not self.ignore_cd:
                        session["path"] = parts[1]
                    for prefix, path in self.path_after_commands.items():
                        if text == prefix or text.startswith(prefix + " "):
                            session["path"] = path
                            break
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
        rendered = re.sub(
            r"#\{@([^}]+)\}",
            lambda match: str(session["metadata"].get(match.group(1), "")),
            rendered,
        )
        return rendered


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

    def test_list_sessions_detects_pi_process_from_pid(self, fake_tmux: FakeTmux, monkeypatch: pytest.MonkeyPatch):
        core.new_session(TEST_SESSION)
        fake_tmux.sessions[TEST_SESSION]["command"] = "node"
        monkeypatch.setattr(core, "_process_command_line", lambda pane_pid="": "pi")

        session = core.list_sessions()[0]

        assert session.process == "pi"

    def test_detect_process_follows_login_shell_children(self, monkeypatch: pytest.MonkeyPatch):
        command_lines = {
            "1000": "-zsh",
            "2000": "node /usr/local/bin/pi --session-dir /tmp/pi",
        }

        monkeypatch.setattr(core, "_raw_process_command_line", lambda pid="": command_lines.get(pid, ""))
        monkeypatch.setattr(core, "_child_pids", lambda pid: ["2000"] if pid == "1000" else [])

        assert core._detect_process("node", pane_pid="1000") == "pi"


class TestMetadata:
    def test_set_and_get(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION)
        core.set_metadata(TEST_SESSION, "status", "running")
        assert core.get_metadata(TEST_SESSION, "status") == "running"
        updated_at = core.get_metadata(TEST_SESSION, "status_updated_at")
        assert updated_at.endswith("Z")

    def test_get_missing_key(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION)
        assert core.get_metadata(TEST_SESSION, "nonexistent") == ""

    def test_overwrite(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION)
        core.set_metadata(TEST_SESSION, "status", "running")
        core.set_metadata(TEST_SESSION, "status", "done")
        assert core.get_metadata(TEST_SESSION, "status") == "done"


class TestDirectoryMetadata:
    def test_infer_session_name_uses_repo_root(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            core,
            "inspect_directory_context",
            lambda directory: {
                "directory": "/repo/worktree/src",
                "repo": "/repo/worktree",
                "branch": "feat/example",
                "origin": "git-worktree",
            },
        )

        assert core.infer_session_name_for_directory("/repo/worktree/src") == "worktree"

    def test_infer_session_name_uses_directory_when_not_in_git(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            core,
            "inspect_directory_context",
            lambda directory: {
                "directory": "/tmp/plain-dir",
                "repo": "/tmp/plain-dir",
                "branch": "",
                "origin": "",
            },
        )

        assert core.infer_session_name_for_directory("/tmp/plain-dir") == "plain-dir"

    def test_uniqueify_session_name_adds_numeric_suffix(self, monkeypatch: pytest.MonkeyPatch):
        existing = {"agentic-trace-analyzer", "agentic-trace-analyzer-1", "agentic-trace-analyzer-2"}
        monkeypatch.setattr(core, "session_exists", lambda name: name in existing)

        assert core.uniqueify_session_name("agentic-trace-analyzer") == "agentic-trace-analyzer-3"

    def test_apply_directory_metadata_uses_git_context(self, monkeypatch: pytest.MonkeyPatch):
        metadata_calls: list[tuple[str, str, str]] = []

        monkeypatch.setattr(core, "_git_root", lambda path: "/repo/worktree")
        monkeypatch.setattr(core, "_detect_git_branch", lambda path: "feat/example")
        monkeypatch.setattr(core, "_is_git_worktree", lambda path: True)
        monkeypatch.setattr(core, "set_metadata", lambda session_name, key, value: metadata_calls.append((session_name, key, value)))

        context = core.apply_directory_metadata(TEST_SESSION, "/repo/worktree")

        assert context == {
            "directory": "/repo/worktree",
            "repo": "/repo/worktree",
            "branch": "feat/example",
            "origin": "git-worktree",
        }
        assert metadata_calls == [
            (TEST_SESSION, "repo", "/repo/worktree"),
            (TEST_SESSION, "branch", "feat/example"),
            (TEST_SESSION, "origin", "git-worktree"),
        ]

    def test_apply_directory_metadata_uses_directory_when_not_in_git(self, monkeypatch: pytest.MonkeyPatch):
        metadata_calls: list[tuple[str, str, str]] = []
        expected_dir = core._normalize_directory("/tmp/plain")

        monkeypatch.setattr(core, "_git_root", lambda path: "")
        monkeypatch.setattr(core, "set_metadata", lambda session_name, key, value: metadata_calls.append((session_name, key, value)))

        context = core.apply_directory_metadata(TEST_SESSION, "/tmp/plain")

        assert context == {
            "directory": expected_dir,
            "repo": expected_dir,
            "branch": "",
            "origin": "",
        }
        assert metadata_calls == [
            (TEST_SESSION, "repo", expected_dir),
        ]


class TestPeekAndSend:
    def test_peek_empty(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION)
        assert core.peek_session(TEST_SESSION, lines=10) == ""

    def test_send_text_sets_last_send_and_peek(self, fake_tmux: FakeTmux):
        core.new_session(TEST_SESSION)
        core.send_text(TEST_SESSION, "echo TMUX_PILOT_TEST_MARKER")
        output = core.peek_session(TEST_SESSION, lines=20)
        assert "TMUX_PILOT_TEST_MARKER" in output
        last_send = fake_tmux.sessions[TEST_SESSION]["metadata"]["last_send"]
        assert isinstance(last_send, str)
        assert last_send.endswith("Z")

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
        assert fake_tmux.sessions[TEST_SESSION]["metadata"]["last_send"].endswith("Z")


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

    def test_wait_until_session_ready_uses_cached_trace_path(
        self,
        fake_tmux: FakeTmux,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ):
        transcript = tmp_path / "rollout.jsonl"
        transcript.write_text(
            '{"timestamp":"2026-03-29T20:00:00Z","type":"session_meta","payload":{"cwd":"/tmp/worktree"}}\n',
            encoding="utf-8",
        )
        core.new_session(TEST_SESSION, directory="/tmp/example")
        fake_tmux.sessions[TEST_SESSION]["command"] = "codex"
        core.set_metadata(TEST_SESSION, "trace_agent", "codex")
        core.set_metadata(TEST_SESSION, "trace_path", str(transcript))
        monkeypatch.setattr(core, "peek_session", lambda name, lines=30: "OpenAI Codex")

        transcript_paths: list[Path | None] = []

        def fake_get_agent_state(*args, **kwargs):
            transcript_paths.append(kwargs.get("transcript_path"))
            return {"type": "codex", "state": "completed", "ready": True}

        monkeypatch.setattr(core, "_get_agent_state", fake_get_agent_state)

        agent = core.wait_until_session_ready(TEST_SESSION, timeout=1.0, interval=0.1)

        assert agent == {"type": "codex", "state": "completed", "ready": True}
        assert transcript_paths == [transcript]


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

    def test_attach_or_switch_execs_tmux_when_attaching_outside_tmux(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        calls: list[str] = []

        monkeypatch.setattr(core, "_is_inside_tmux", lambda: False)
        monkeypatch.setattr(core, "_exec_tmux_attach", lambda target: calls.append(target))

        core._attach_or_switch("demo")

        assert calls == ["demo"]


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


class TestTrace:
    def test_get_session_trace_discovers_and_caches_transcript(
        self,
        fake_tmux: FakeTmux,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ):
        transcript = tmp_path / "rollout.jsonl"
        transcript.write_text(
            "\n".join(
                [
                    '{"timestamp":"2026-03-29T20:00:00Z","type":"session_meta","payload":{"cwd":"/tmp/example"}}',
                    '{"timestamp":"2026-03-29T20:00:01Z","type":"event_msg","payload":{"type":"task_complete","turn_id":"turn-3"}}',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        core.new_session(TEST_SESSION, directory="/tmp/example")
        fake_tmux.sessions[TEST_SESSION]["command"] = "codex"
        monkeypatch.setattr(agent_sessions, "find_transcript_for_cwd", lambda agent_type, cwd, limit=200: transcript)

        trace = core.get_session_trace(TEST_SESSION)

        assert trace["agent"] == "codex"
        assert trace["path"] == str(transcript.resolve())
        assert trace["source"] == "dynamic"
        assert trace["transcript_cwd"] == str(Path("/tmp/example").resolve())
        assert trace["state"] == "completed"
        assert fake_tmux.sessions[TEST_SESSION]["metadata"]["trace_agent"] == "codex"
        assert fake_tmux.sessions[TEST_SESSION]["metadata"]["trace_path"] == str(transcript.resolve())

    def test_get_session_trace_prefers_cached_binding_over_pane_cwd(
        self,
        fake_tmux: FakeTmux,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ):
        transcript = tmp_path / "rollout.jsonl"
        transcript.write_text(
            '{"timestamp":"2026-03-29T20:00:00Z","type":"session_meta","payload":{"cwd":"/tmp/worktree"}}\n',
            encoding="utf-8",
        )
        core.new_session(TEST_SESSION, directory="/tmp/main")
        fake_tmux.sessions[TEST_SESSION]["command"] = "codex"
        core.set_metadata(TEST_SESSION, "trace_agent", "codex")
        core.set_metadata(TEST_SESSION, "trace_path", str(transcript))

        calls: list[tuple[str, str]] = []

        def fake_find(agent_type: str, cwd: str, limit: int = 200):
            calls.append((agent_type, cwd))
            return None

        monkeypatch.setattr(agent_sessions, "find_transcript_for_cwd", fake_find)

        trace = core.get_session_trace(TEST_SESSION)

        assert trace["source"] == "cached"
        assert trace["transcript_cwd"] == str(Path("/tmp/worktree").resolve())
        assert calls == []

    def test_get_session_status_exposes_trace_info(
        self,
        fake_tmux: FakeTmux,
        tmp_path,
    ):
        transcript = tmp_path / "rollout.jsonl"
        transcript.write_text(
            '{"timestamp":"2026-03-29T20:00:00Z","type":"session_meta","payload":{"cwd":"/tmp/worktree"}}\n',
            encoding="utf-8",
        )
        core.new_session(TEST_SESSION, directory="/tmp/main")
        fake_tmux.sessions[TEST_SESSION]["command"] = "codex"
        core.set_metadata(TEST_SESSION, "trace_agent", "codex")
        core.set_metadata(TEST_SESSION, "trace_path", str(transcript))

        info = core.get_session_status(TEST_SESSION)

        assert info["trace"]["path"] == str(transcript.resolve())
        assert info["metadata"]["trace_agent"] == "codex"
        assert info["metadata"]["trace_path"] == str(transcript.resolve())


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

    def test_cols_support_review_and_merge_state(self):
        result = format_session_table(
            [
                core.SessionInfo(
                    name="s1",
                    metadata={"pr_review": "APPROVED", "pr_merge_state": "CLEAN"},
                )
            ],
            cols="NAME,REVIEW,MERGE_STATE",
        )
        assert "REVIEW" in result
        assert "MERGE_STATE" in result
        assert "APPROVED" in result
        assert "CLEAN" in result

    def test_pr_column_compacts_review_and_merge_codes(self):
        result = format_session_table(
            [
                core.SessionInfo(
                    name="s1",
                    metadata={
                        "pr": "1548",
                        "pr_state": "OPEN",
                        "pr_review": "REVIEW_REQUIRED",
                        "pr_merge_state": "DIRTY",
                    },
                )
            ],
            cols="NAME,PR",
        )
        assert "PR" in result
        assert "1548 RR D" in result

    def test_pr_column_shows_merged_compactly(self):
        result = format_session_table(
            [
                core.SessionInfo(
                    name="s1",
                    metadata={
                        "pr": "1547",
                        "pr_state": "MERGED",
                        "pr_review": "APPROVED",
                        "pr_merge_state": "UNKNOWN",
                    },
                )
            ],
            cols="NAME,PR",
        )
        assert "1547 M" in result
        assert "UNKNOWN" not in result

    def test_all_metadata_appends_known_metadata_columns(self):
        result = format_session_table(
            [
                core.SessionInfo(
                    name="s1",
                    process="codex",
                    working_dir="/tmp",
                    metadata={
                        "status": "active",
                        "origin": "git-worktree",
                        "last_refresh": "2026-04-19T22:15:00Z",
                        "pr_state": "OPEN",
                        "trace_agent": "codex",
                    },
                )
            ],
            cols="NAME",
            all_metadata=True,
        )
        assert "ORIGIN" in result
        assert "LAST_REFRESH" in result
        assert "PR_STATE" in result
        assert "TRACE_AGENT" in result
        assert "git-worktree" in result

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

    def test_format_status_shows_metadata_update_ages(self):
        rendered = format_status(
            {
                "name": "alpha",
                "process": "codex",
                "pid": "123",
                "working_dir": "/tmp/alpha",
                "metadata": {
                    "status": "active",
                    "pr": "42",
                    "last_refresh": "2026-04-19T22:58:00Z",
                },
                "metadata_updated_at": {
                    "status": "2026-04-19T22:00:00Z",
                },
                "agent": {},
            },
            now=datetime(2026, 4, 19, 23, 0, tzinfo=timezone.utc),
        )

        assert "@status = active (updated 1h ago)" in rendered
        assert "@pr = 42 (updated 2m ago)" in rendered
        assert "@last_refresh = 2026-04-19T22:58:00Z" in rendered

    def test_format_status_hides_unknown_merge_state(self):
        rendered = format_status(
            {
                "name": "alpha",
                "process": "codex",
                "pid": "123",
                "working_dir": "/tmp/alpha",
                "metadata": {
                    "pr": "42",
                    "pr_state": "MERGED",
                    "pr_merge_state": "UNKNOWN",
                },
                "metadata_updated_at": {},
                "agent": {},
            }
        )

        assert "@pr_state = MERGED" in rendered
        assert "@pr_merge_state" not in rendered


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
        output = capsys.readouterr().out
        assert output.startswith("tp ")
        assert "0.0.0" not in output

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

    def test_refresh_json(self, monkeypatch: pytest.MonkeyPatch, capsys):
        monkeypatch.setattr(
            reaper,
            "refresh_pr_metadata",
            lambda names=None, repo=None: [
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
            ],
        )

        cli_main(["refresh", "--json"])

        data = json.loads(capsys.readouterr().out)
        assert data[0]["session"] == "alpha"
        assert data[0]["pr_merge_state"] == "CLEAN"

    def test_refresh_named_subset(self, monkeypatch: pytest.MonkeyPatch, capsys):
        calls: list[tuple[list[str] | None, str | None]] = []

        def refresh_pr_metadata(*, names=None, repo=None):
            calls.append((names, repo))
            return [
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

        monkeypatch.setattr(reaper, "refresh_pr_metadata", refresh_pr_metadata)

        cli_main(["refresh", "alpha"])

        assert calls == [(["alpha"], None)]
        out = capsys.readouterr().out
        assert "alpha" in out
        assert "review=APPROVED" in out
        assert "merge=CLEAN" in out

    def test_refresh_repo_filter(self, monkeypatch: pytest.MonkeyPatch, capsys):
        calls: list[tuple[list[str] | None, str | None]] = []

        def refresh_pr_metadata(*, names=None, repo=None):
            calls.append((names, repo))
            return []

        monkeypatch.setattr(reaper, "refresh_pr_metadata", refresh_pr_metadata)

        cli_main(["refresh", "--repo", "dismech"])

        assert calls == [(None, "dismech")]
        assert "No sessions to refresh." in capsys.readouterr().out

    def test_trace_json(self, monkeypatch: pytest.MonkeyPatch, capsys):
        monkeypatch.setattr(
            core,
            "get_session_trace",
            lambda name, refresh=False, lines=0: {
                "session": name,
                "agent": "codex",
                "path": "/tmp/trace.jsonl",
                "source": "cached",
                "pane_working_dir": "/tmp/worktree",
                "transcript_cwd": "/tmp/worktree",
                "state": "completed",
                "timestamp": "2026-04-20T00:00:00Z",
                "turn_id": "turn-9",
                "tail": ['{"type":"event_msg"}'],
            },
        )

        cli_main(["trace", "alpha", "--json", "--lines", "1"])

        data = json.loads(capsys.readouterr().out)
        assert data["agent"] == "codex"
        assert data["path"] == "/tmp/trace.jsonl"

    def test_trace_show_raw(self, monkeypatch: pytest.MonkeyPatch, capsys, tmp_path):
        transcript = tmp_path / "trace.jsonl"
        transcript.write_text('{"type":"user"}\n{"type":"assistant"}\n', encoding="utf-8")
        monkeypatch.setattr(
            core,
            "get_session_trace",
            lambda name, refresh=False, lines=0: {
                "session": name,
                "agent": "codex",
                "path": str(transcript),
                "source": "cached",
                "pane_working_dir": "/tmp/worktree",
                "transcript_cwd": "/tmp/worktree",
                "state": "completed",
                "timestamp": "2026-04-20T00:00:00Z",
                "turn_id": "turn-9",
                "tail": [],
            },
        )

        cli_main(["trace", "alpha", "--show", "raw", "--lines", "1"])

        assert capsys.readouterr().out.strip() == '{"type":"assistant"}'

    def test_trace_show_json_uses_pretty_records(self, monkeypatch: pytest.MonkeyPatch, capsys, tmp_path):
        transcript = tmp_path / "trace.jsonl"
        transcript.write_text('{"type":"user","message":"hello"}\n', encoding="utf-8")
        monkeypatch.setattr(
            core,
            "get_session_trace",
            lambda name, refresh=False, lines=0: {
                "session": name,
                "agent": "codex",
                "path": str(transcript),
                "source": "cached",
                "pane_working_dir": "/tmp/worktree",
                "transcript_cwd": "/tmp/worktree",
                "state": "completed",
                "timestamp": "2026-04-20T00:00:00Z",
                "turn_id": "turn-9",
                "tail": [],
            },
        )

        cli_main(["trace", "alpha", "--show", "json"])

        data = json.loads(capsys.readouterr().out)
        assert data == [{"type": "user", "message": "hello"}]

    def test_trace_show_json_color_always_emits_ansi(self, monkeypatch: pytest.MonkeyPatch, capsys, tmp_path):
        transcript = tmp_path / "trace.jsonl"
        transcript.write_text('{"type":"user","message":"hello"}\n', encoding="utf-8")
        monkeypatch.setattr(
            core,
            "get_session_trace",
            lambda name, refresh=False, lines=0: {
                "session": name,
                "agent": "codex",
                "path": str(transcript),
                "source": "cached",
                "pane_working_dir": "/tmp/worktree",
                "transcript_cwd": "/tmp/worktree",
                "state": "completed",
                "timestamp": "2026-04-20T00:00:00Z",
                "turn_id": "turn-9",
                "tail": [],
            },
        )

        cli_main(["trace", "alpha", "--show", "json", "--color", "always"])

        out = capsys.readouterr().out
        assert "\x1b[" in out
        assert '"type"' in out

    def test_trace_show_json_color_auto_respects_non_tty(self, monkeypatch: pytest.MonkeyPatch, capsys, tmp_path):
        transcript = tmp_path / "trace.jsonl"
        transcript.write_text('{"type":"user","message":"hello"}\n', encoding="utf-8")
        monkeypatch.setattr(
            core,
            "get_session_trace",
            lambda name, refresh=False, lines=0: {
                "session": name,
                "agent": "codex",
                "path": str(transcript),
                "source": "cached",
                "pane_working_dir": "/tmp/worktree",
                "transcript_cwd": "/tmp/worktree",
                "state": "completed",
                "timestamp": "2026-04-20T00:00:00Z",
                "turn_id": "turn-9",
                "tail": [],
            },
        )
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

        cli_main(["trace", "alpha", "--show", "json", "--color", "auto"])

        out = capsys.readouterr().out
        assert "\x1b[" not in out
        data = json.loads(out)
        assert data == [{"type": "user", "message": "hello"}]

    def test_trace_show_yaml_handles_claude_records(self, monkeypatch: pytest.MonkeyPatch, capsys, tmp_path):
        transcript = tmp_path / "trace.jsonl"
        transcript.write_text(
            '{"cwd":"/tmp/project","sessionId":"claude-1","type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"done"}]}}\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            core,
            "get_session_trace",
            lambda name, refresh=False, lines=0: {
                "session": name,
                "agent": "claude-code",
                "path": str(transcript),
                "source": "cached",
                "pane_working_dir": "/tmp/project",
                "transcript_cwd": "/tmp/project",
                "state": "completed",
                "timestamp": "2026-04-20T00:00:00Z",
                "turn_id": "msg-9",
                "tail": [],
            },
        )

        cli_main(["trace", "alpha", "--show", "yaml"])

        out = capsys.readouterr().out
        assert "sessionId: \"claude-1\"" in out
        assert "role: \"assistant\"" in out
        assert "text: \"done\"" in out

    def test_trace_show_tsv_handles_claude_records(self, monkeypatch: pytest.MonkeyPatch, capsys, tmp_path):
        transcript = tmp_path / "trace.jsonl"
        transcript.write_text(
            '{"cwd":"/tmp/project","sessionId":"claude-1","type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{"command":"pwd"}}]},"uuid":"msg-2","timestamp":"2026-03-29T20:00:02Z"}\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            core,
            "get_session_trace",
            lambda name, refresh=False, lines=0: {
                "session": name,
                "agent": "claude-code",
                "path": str(transcript),
                "source": "cached",
                "pane_working_dir": "/tmp/project",
                "transcript_cwd": "/tmp/project",
                "state": "running",
                "timestamp": "2026-04-20T00:00:00Z",
                "turn_id": "msg-2",
                "tail": [],
            },
        )

        cli_main(["trace", "alpha", "--show", "tsv"])

        out = capsys.readouterr().out.strip().splitlines()
        assert out[0] == "timestamp\tkind\trole\tturn_id\tsummary"
        assert out[1] == "2026-03-29T20:00:02Z\tassistant\tassistant\tmsg-2\ttool Bash: pwd"

    def test_trace_show_formatted_handles_codex_records(self, monkeypatch: pytest.MonkeyPatch, capsys, tmp_path):
        transcript = tmp_path / "trace.jsonl"
        transcript.write_text(
            "\n".join(
                [
                    '{"timestamp":"2026-03-29T20:00:00Z","type":"session_meta","payload":{"cwd":"/tmp/project"}}',
                    '{"timestamp":"2026-03-29T20:00:01Z","type":"event_msg","payload":{"type":"task_started","turn_id":"turn-1"}}',
                    '{"timestamp":"2026-03-29T20:00:02Z","type":"event_msg","payload":{"type":"task_complete","turn_id":"turn-1"}}',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            core,
            "get_session_trace",
            lambda name, refresh=False, lines=0: {
                "session": name,
                "agent": "codex",
                "path": str(transcript),
                "source": "cached",
                "pane_working_dir": "/tmp/project",
                "transcript_cwd": "/tmp/project",
                "state": "completed",
                "timestamp": "2026-04-20T00:00:00Z",
                "turn_id": "turn-1",
                "tail": [],
            },
        )

        cli_main(["trace", "alpha", "--show", "formatted", "--color", "never"])

        out = capsys.readouterr().out
        assert "2026-03-29T20:00:00Z  session" in out
        assert "cwd=/tmp/project" in out
        assert "2026-03-29T20:00:01Z  event" in out
        assert "[turn-1]  task_started" in out
        assert "[turn-1]  task_complete" in out

    def test_trace_human_output_when_missing(self, monkeypatch: pytest.MonkeyPatch, capsys):
        monkeypatch.setattr(
            core,
            "get_session_trace",
            lambda name, refresh=False, lines=0: {
                "session": name,
                "agent": "codex",
                "path": "",
                "source": "none",
                "pane_working_dir": "/tmp/worktree",
                "transcript_cwd": "",
                "state": "",
                "timestamp": "",
                "turn_id": "",
                "tail": [],
            },
        )

        cli_main(["trace", "alpha"])

        assert "No transcript trace found for session 'alpha'." in capsys.readouterr().out

    def test_ls_all_metadata(self, fake_tmux: FakeTmux, capsys):
        core.new_session(TEST_SESSION, desc="metadata test")
        core.set_metadata(TEST_SESSION, "origin", "git-worktree")
        core.set_metadata(TEST_SESSION, "last_refresh", "2026-04-19T22:15:00Z")

        cli_main(["ls", "--all-metadata"])

        out = capsys.readouterr().out
        assert "LAST_REFRESH" in out
        assert "ORIGIN" in out
        assert "git-worktree" in out

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

    def test_prod_dry_run(self, monkeypatch: pytest.MonkeyPatch, capsys):
        monkeypatch.setattr(
            core,
            "plan_prod_actions",
            lambda **kwargs: [
                {
                    "session": TEST_SESSION,
                    "pr": "1614",
                    "pr_review": "CHANGES_REQUESTED",
                    "pr_merge_state": "BLOCKED",
                    "skipped": False,
                    "rule": "changes-requested",
                    "prompt": "Address all requested review comments.",
                },
                {
                    "session": "idle",
                    "skipped": True,
                    "reason": "no-rule",
                },
            ],
        )
        send_calls: list[tuple[str, str, bool, float]] = []
        monkeypatch.setattr(
            core,
            "send_text",
            lambda name, text, *, wait, timeout, interval=0.25: send_calls.append((name, text, wait, timeout)),
        )

        cli_main(["prod", "--dry-run", TEST_SESSION, "idle"])

        out = capsys.readouterr().out
        assert "rule=changes-requested" in out
        assert "Address all requested review comments." in out
        assert "idle  skipped (no-rule)" in out
        assert "Planned 1 prod message(s)." in out
        assert send_calls == []

    def test_prod_sends_prompts(self, monkeypatch: pytest.MonkeyPatch, capsys):
        monkeypatch.setattr(
            core,
            "plan_prod_actions",
            lambda **kwargs: [
                {
                    "session": TEST_SESSION,
                    "pr": "1614",
                    "pr_review": "CHANGES_REQUESTED",
                    "pr_merge_state": "BLOCKED",
                    "skipped": False,
                    "rule": "changes-requested",
                    "prompt": "Address all requested review comments.",
                }
            ],
        )
        send_calls: list[tuple[str, str, bool, float]] = []

        def send_text(name: str, text: str, *, wait: bool, timeout: float, interval: float = 0.25):
            del interval
            send_calls.append((name, text, wait, timeout))
            return {"type": "codex", "state": "completed", "ready": True}

        monkeypatch.setattr(core, "send_text", send_text)

        cli_main(["prod", "--timeout", "12", TEST_SESSION])

        assert send_calls == [(TEST_SESSION, "Address all requested review comments.", False, 12.0)]
        assert "Sent 1 prod message(s)." in capsys.readouterr().out

    def test_prod_with_wait_keeps_timeout_strict(self, monkeypatch: pytest.MonkeyPatch, capsys):
        monkeypatch.setattr(
            core,
            "plan_prod_actions",
            lambda **kwargs: [
                {
                    "session": TEST_SESSION,
                    "pr": "1614",
                    "pr_review": "CHANGES_REQUESTED",
                    "pr_merge_state": "DIRTY",
                    "skipped": False,
                    "rule": "changes-requested",
                    "prompt": "Address all requested review comments.",
                }
            ],
        )

        def send_text(name: str, text: str, *, wait: bool, timeout: float, interval: float = 0.25):
            del name, text, wait, timeout, interval
            raise core.AgentWaitTimeout(TEST_SESSION, "running")

        monkeypatch.setattr(core, "send_text", send_text)

        with pytest.raises(SystemExit) as exc_info:
            cli_main(["prod", "--wait", TEST_SESSION])

        assert exc_info.value.code == 1
        assert "Timed out waiting for session" in capsys.readouterr().err

    def test_prod_reports_config_errors(self, monkeypatch: pytest.MonkeyPatch, capsys):
        monkeypatch.setattr(core, "plan_prod_actions", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("no rules")))

        with pytest.raises(SystemExit) as exc_info:
            cli_main(["prod"])

        assert exc_info.value.code == 1
        assert "no rules" in capsys.readouterr().err

    def test_new_with_agent_and_prompt_uses_plain_mode(self, monkeypatch: pytest.MonkeyPatch, capsys):
        new_calls: list[tuple[str, str | None, str | None]] = []
        launch_calls: list[tuple[str, str, str | None, str | None]] = []

        monkeypatch.setattr(core, "session_exists", lambda name: False)
        monkeypatch.setattr(core, "load_profiles", lambda path=None: {})
        monkeypatch.setattr(
            core,
            "new_session",
            lambda name, *, directory=None, desc=None, command=None: new_calls.append((name, directory, desc)),
        )
        monkeypatch.setattr(
            core,
            "launch_agent_session",
            lambda session_name, command, *, prompt=None, expected_cwd=None, prompt_timeout=30.0: launch_calls.append((session_name, command, prompt, expected_cwd)),
        )
        monkeypatch.setattr(
            core,
            "create_profile_session",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not use profile mode")),
        )

        cli_main(["new", "foo-codex-test-4", "--agent", "codex", "--prompt", "1+3"])

        assert new_calls == [("foo-codex-test-4", None, None)]
        assert launch_calls == [("foo-codex-test-4", "codex", "1+3", None)]
        assert "Created session 'foo-codex-test-4'" in capsys.readouterr().out

    def test_new_with_agent_and_directory_passes_expected_cwd(self, monkeypatch: pytest.MonkeyPatch, capsys):
        launch_calls: list[tuple[str, str, str | None, str | None]] = []
        expected_cwd = "/tmp/worktree"

        monkeypatch.setattr(core, "session_exists", lambda name: False)
        monkeypatch.setattr(core, "load_profiles", lambda path=None: {})
        monkeypatch.setattr(core, "new_session", lambda name, *, directory=None, desc=None, command=None: None)
        monkeypatch.setattr(
            core,
            "launch_agent_session",
            lambda session_name, command, *, prompt=None, expected_cwd=None, prompt_timeout=30.0: launch_calls.append((session_name, command, prompt, expected_cwd)),
        )

        cli_main(["new", "foo", "-c", expected_cwd, "--agent", "codex"])

        assert launch_calls == [("foo", "codex", None, expected_cwd)]
        assert "Created session 'foo'" in capsys.readouterr().out

    def test_new_with_here_applies_directory_metadata_and_can_jump(self, monkeypatch: pytest.MonkeyPatch):
        launch_calls: list[tuple[str, str, str | None, str | None]] = []
        metadata_calls: list[tuple[str, str]] = []
        jump_calls: list[str] = []
        current_dir = "/tmp/worktree"

        monkeypatch.setattr(core, "session_exists", lambda name: False)
        monkeypatch.setattr(core, "load_profiles", lambda path=None: {})
        monkeypatch.setattr(core, "new_session", lambda name, *, directory=None, desc=None, command=None: None)
        monkeypatch.setattr(core, "infer_session_name_for_directory", lambda directory: "worktree")
        monkeypatch.setattr(core, "apply_directory_metadata", lambda session_name, directory: metadata_calls.append((session_name, directory)) or {})
        monkeypatch.setattr(
            core,
            "launch_agent_session",
            lambda session_name, command, *, prompt=None, expected_cwd=None, prompt_timeout=30.0: launch_calls.append((session_name, command, prompt, expected_cwd)),
        )
        monkeypatch.setattr(core, "jump_session", lambda name: jump_calls.append(name))
        monkeypatch.setattr("tmux_pilot.cli.os.getcwd", lambda: current_dir)

        cli_main(["new", "--here", "--agent", "codex", "--jump"])

        assert metadata_calls == [("worktree", current_dir)]
        assert launch_calls == [("worktree", "codex", None, current_dir)]
        assert jump_calls == ["worktree"]

    def test_new_here_conflicts_with_directory(self, monkeypatch: pytest.MonkeyPatch, capsys):
        monkeypatch.setattr(core, "session_exists", lambda name: False)

        with pytest.raises(SystemExit) as exc_info:
            cli_main(["new", "foo", "--here", "-c", "/tmp/other"])

        assert exc_info.value.code == 1
        assert "--here cannot be combined with --directory" in capsys.readouterr().err

    def test_new_without_name_uses_directory_name(self, monkeypatch: pytest.MonkeyPatch, capsys):
        new_calls: list[tuple[str, str | None, str | None]] = []

        monkeypatch.setattr(core, "session_exists", lambda name: False)
        monkeypatch.setattr(core, "load_profiles", lambda path=None: {})
        monkeypatch.setattr(core, "infer_session_name_for_directory", lambda directory: "my-worktree")
        monkeypatch.setattr(
            core,
            "new_session",
            lambda name, *, directory=None, desc=None, command=None: new_calls.append((name, directory, desc)),
        )

        cli_main(["new", "-c", "/tmp/my-worktree"])

        assert new_calls == [("my-worktree", "/tmp/my-worktree", None)]
        assert "Created session 'my-worktree'" in capsys.readouterr().out

    def test_new_with_directory_uses_default_profile_mode(self, monkeypatch: pytest.MonkeyPatch, capsys):
        create_calls: list[tuple[str, dict[str, object]]] = []
        new_calls: list[str] = []

        monkeypatch.setattr(core, "session_exists", lambda name: False)
        monkeypatch.setattr(
            core,
            "load_profiles",
            lambda path=None: {"default": core.SessionProfile(name="default", command=("codex", "--profile", "yolo"))},
        )
        monkeypatch.setattr(
            core,
            "create_profile_session",
            lambda name, **kwargs: create_calls.append((name, kwargs)),
        )
        monkeypatch.setattr(
            core,
            "new_session",
            lambda name, *, directory=None, desc=None, command=None: new_calls.append(name),
        )

        cli_main(["new", "rename-types", "-c", "/tmp/myapp"])

        assert create_calls == [
            (
                "rename-types",
                {
                    "profile_name": None,
                    "issue": None,
                    "agent": None,
                    "repo": None,
                    "directory": "/tmp/myapp",
                    "branch": None,
                    "base_ref": None,
                    "no_agent": False,
                    "prompt": None,
                    "desc": None,
                },
            )
        ]
        assert new_calls == []
        assert "Created session 'rename-types'" in capsys.readouterr().out

    def test_new_without_name_auto_uniqueifies_inferred_name(self, monkeypatch: pytest.MonkeyPatch, capsys):
        new_calls: list[tuple[str, str | None, str | None]] = []
        existing = {"agentic-trace-analyzer", "agentic-trace-analyzer-1"}
        current_dir = "/tmp/agentic-trace-analyzer"

        monkeypatch.setattr(core, "session_exists", lambda name: name in existing)
        monkeypatch.setattr(core, "load_profiles", lambda path=None: {})
        monkeypatch.setattr(core, "infer_session_name_for_directory", lambda directory: "agentic-trace-analyzer")
        monkeypatch.setattr("tmux_pilot.cli.os.getcwd", lambda: current_dir)
        monkeypatch.setattr(core, "apply_directory_metadata", lambda session_name, directory: {})
        monkeypatch.setattr(
            core,
            "new_session",
            lambda name, *, directory=None, desc=None, command=None: new_calls.append((name, directory, desc)),
        )

        cli_main(["new", "--here"])

        assert new_calls == [("agentic-trace-analyzer-2", current_dir, None)]
        assert "Created session 'agentic-trace-analyzer-2'" in capsys.readouterr().out

    def test_new_without_name_errors_when_no_directory_context(self, monkeypatch: pytest.MonkeyPatch, capsys):
        monkeypatch.setattr(core, "session_exists", lambda name: False)
        monkeypatch.setattr(core, "load_profiles", lambda path=None: {})

        with pytest.raises(SystemExit) as exc_info:
            cli_main(["new"])

        assert exc_info.value.code == 1
        assert "Session name is required unless --directory or --here is provided." in capsys.readouterr().err

    def test_launch_agent_session_waits_before_prompt(self, monkeypatch: pytest.MonkeyPatch):
        send_keys_calls: list[tuple[str, str]] = []
        send_text_calls: list[tuple[str, str, bool, float]] = []
        metadata_calls: list[tuple[str, str, str]] = []

        monkeypatch.setattr(core, "send_keys", lambda name, text: send_keys_calls.append((name, text)))
        monkeypatch.setattr(core, "set_metadata", lambda name, key, value: metadata_calls.append((name, key, value)))
        monkeypatch.setattr(
            core,
            "send_text",
            lambda name, text, *, wait=False, timeout=30.0, interval=0.25: send_text_calls.append((name, text, wait, timeout)) or {},
        )

        core.launch_agent_session(TEST_SESSION, "codex", prompt="1+3", prompt_timeout=12.0)

        assert send_keys_calls == [(TEST_SESSION, "codex")]
        assert send_text_calls == [(TEST_SESSION, "1+3", True, 12.0)]
        assert metadata_calls == [(TEST_SESSION, "trace_agent", "codex")]

    def test_launch_agent_session_reports_undelivered_initial_prompt(self, monkeypatch: pytest.MonkeyPatch):
        send_keys_calls: list[tuple[str, str]] = []

        monkeypatch.setattr(core, "send_keys", lambda name, text: send_keys_calls.append((name, text)))
        monkeypatch.setattr(core, "set_metadata", lambda *args: None)

        def raise_timeout(name: str, text: str, *, wait: bool = False, timeout: float = 30.0, interval: float = 0.25):
            del name, text, wait, timeout, interval
            raise RuntimeError(f"Timed out waiting for session '{TEST_SESSION}' to become ready (last state: running)")

        monkeypatch.setattr(core, "send_text", raise_timeout)

        with pytest.raises(RuntimeError) as exc_info:
            core.launch_agent_session(TEST_SESSION, "codex", prompt="write note.txt alpha")

        message = str(exc_info.value)
        assert send_keys_calls == [(TEST_SESSION, "codex")]
        assert "Initial prompt was not delivered" in message
        assert f"tp send --wait {TEST_SESSION} 'write note.txt alpha'" in message
        assert "startup modal or trust prompt" in message

    def test_launch_agent_session_restores_expected_cwd_before_launch(self, fake_tmux: FakeTmux, tmp_path):
        expected_cwd = str(tmp_path)
        core.new_session(TEST_SESSION, directory=expected_cwd)
        fake_tmux.sessions[TEST_SESSION]["path"] = "/Users/cjm"

        core.launch_agent_session(TEST_SESSION, "codex", expected_cwd=expected_cwd)

        assert fake_tmux.sessions[TEST_SESSION]["path"] == expected_cwd
        assert fake_tmux.send_key_calls == [
            (TEST_SESSION, True, [f"cd {shlex.quote(expected_cwd)}"]),
            (TEST_SESSION, False, ["Enter"]),
            (TEST_SESSION, True, ["codex"]),
            (TEST_SESSION, False, ["Enter"]),
        ]

    def test_launch_agent_session_raises_when_cwd_cannot_be_restored(
        self,
        fake_tmux: FakeTmux,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        expected_cwd = str(tmp_path)
        core.new_session(TEST_SESSION, directory=expected_cwd)
        fake_tmux.sessions[TEST_SESSION]["path"] = "/Users/cjm"
        fake_tmux.ignore_cd = True
        monkeypatch.setattr(core.time, "sleep", lambda seconds: None)
        monotonic_values = iter([0.0, 0.5, 1.0, 3.0])
        monkeypatch.setattr(core.time, "monotonic", lambda: next(monotonic_values))

        with pytest.raises(RuntimeError, match="will not launch the agent"):
            core.launch_agent_session(TEST_SESSION, "codex", expected_cwd=expected_cwd)

        assert fake_tmux.send_key_calls == [
            (TEST_SESSION, True, [f"cd {shlex.quote(expected_cwd)}"]),
            (TEST_SESSION, False, ["Enter"]),
        ]

    def test_launch_agent_session_raises_when_agent_changes_cwd_after_launch(
        self,
        fake_tmux: FakeTmux,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        expected_cwd = str(tmp_path)
        fake_tmux.path_after_commands["codex"] = "/Users/cjm"
        core.new_session(TEST_SESSION, directory=expected_cwd)
        monkeypatch.setattr(core.time, "sleep", lambda seconds: None)
        monotonic_values = iter([0.0, 0.5, 1.0, 3.0])
        monkeypatch.setattr(core.time, "monotonic", lambda: next(monotonic_values))

        with pytest.raises(RuntimeError, match="changed to"):
            core.launch_agent_session(TEST_SESSION, "codex", expected_cwd=expected_cwd)

    def test_new_prompt_without_agent_errors_in_plain_mode(self, monkeypatch: pytest.MonkeyPatch, capsys):
        monkeypatch.setattr(core, "session_exists", lambda name: False)
        monkeypatch.setattr(core, "load_profiles", lambda path=None: {})

        with pytest.raises(SystemExit) as exc_info:
            cli_main(["new", "foo", "--prompt", "1+3"])

        assert exc_info.value.code == 1
        assert "--prompt requires --agent in plain mode" in capsys.readouterr().err
