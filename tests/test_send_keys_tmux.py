"""Integration tests for send_keys against a real tmux server."""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from tmux_pilot import core
from tmux_pilot.cli import main as cli_main


MOCK_CODEX = Path(__file__).resolve().parent / "support" / "mock_codex_like.py"
MOCK_CLAUDE = Path(__file__).resolve().parent / "support" / "mock_claude_code_like.py"


class RealTmuxServer:
    def __init__(self, socket_name: str) -> None:
        self.socket_name = socket_name

    def _command(self, *args: str) -> list[str]:
        return ["tmux", "-L", self.socket_name, "-f", "/dev/null", *args]

    def run(
        self,
        *args: str,
        check: bool = True,
        capture_output: bool = True,
        cwd: str | None = None,
        timeout: int = 5,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self._command(*args),
            check=check,
            capture_output=capture_output,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )

    def send_literal(self, session_name: str, text: str) -> None:
        self.run("send-keys", "-t", session_name, "-l", text)

    def send_enter(self, session_name: str) -> None:
        self.run("send-keys", "-t", session_name, "Enter")


@pytest.fixture
def real_tmux(monkeypatch: pytest.MonkeyPatch) -> RealTmuxServer:
    if shutil.which("tmux") is None:
        pytest.skip("tmux is required for send_keys integration tests")

    server = RealTmuxServer(f"tp-test-{uuid.uuid4().hex}")

    def run(
        args: list[str],
        *,
        check: bool = True,
        capture: bool = True,
        cwd: str | None = None,
        timeout: int = 5,
    ) -> subprocess.CompletedProcess[str]:
        if not args or args[0] != "tmux":
            return subprocess.run(
                args,
                check=check,
                capture_output=capture,
                text=True,
                cwd=cwd,
                timeout=timeout,
            )
        return server.run(
            *args[1:],
            check=check,
            capture_output=capture,
            cwd=cwd,
            timeout=timeout,
        )

    monkeypatch.setattr(core, "_run", run)
    try:
        yield server
    finally:
        server.run("kill-server", check=False)


def wait_for(predicate, *, timeout: float = 3.0, interval: float = 0.05, message: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(message)


def wait_for_output(session_name: str, text: str, *, timeout: float = 3.0) -> str:
    output = ""

    def has_text() -> bool:
        nonlocal output
        output = core.peek_session(session_name, lines=200)
        return text in output

    try:
        wait_for(has_text, timeout=timeout, message=f"timed out waiting for {text!r} in tmux output")
    except AssertionError as exc:
        raise AssertionError(f"{exc}\nLast tmux output:\n{output}") from exc
    return output


def launch_mock_codex(session_name: str, workdir: Path) -> None:
    command = f"{shlex.quote(sys.executable)} -u {shlex.quote(str(MOCK_CODEX))}"
    core._run(
        ["tmux", "new-session", "-d", "-s", session_name, "-c", str(workdir), command],
        check=True,
    )
    wait_for_output(session_name, "Press enter")


def launch_mock_claude(session_name: str, workdir: Path) -> None:
    command = f"{shlex.quote(sys.executable)} -u {shlex.quote(str(MOCK_CLAUDE))}"
    core._run(
        ["tmux", "new-session", "-d", "-s", session_name, "-c", str(workdir), command],
        check=True,
    )
    wait_for_output(session_name, "Claude Code mock")


def test_real_tmux_mock_codex_requires_extra_enter_without_settle_delay(real_tmux: RealTmuxServer, tmp_path: Path):
    session = "mock-codex-no-delay"
    launch_mock_codex(session, tmp_path)

    real_tmux.send_literal(session, "1")
    real_tmux.send_enter(session)
    time.sleep(0.2)

    output = core.peek_session(session, lines=200)
    assert "TRUSTED" not in output
    assert "Press enter" in output

    real_tmux.send_enter(session)
    wait_for_output(session, "TRUSTED")


def test_core_send_keys_submits_mock_codex_commands_with_real_tmux(real_tmux: RealTmuxServer, tmp_path: Path):
    session = "mock-codex-core-send"
    launch_mock_codex(session, tmp_path)

    core.send_keys(session, "1")
    wait_for_output(session, "TRUSTED")

    core.send_keys(session, "write note.txt alpha")
    note = tmp_path / "note.txt"
    wait_for(note.exists, message="timed out waiting for note.txt to be created")
    wait_for(lambda: note.read_text() == "alpha\n", message="timed out waiting for note.txt contents")

    core.send_keys(session, "append note.txt beta")
    wait_for(lambda: note.read_text() == "alpha\nbeta\n", message="timed out waiting for append")

    core.send_keys(session, "count note.txt")
    output = wait_for_output(session, "COUNT 2")
    assert "COUNT 2" in output


def test_cli_send_wait_uses_codex_transcript_state_with_real_tmux(
    real_tmux: RealTmuxServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    session = "mock-codex-send-wait"
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    launch_mock_codex(session, tmp_path)

    core.send_keys(session, "1")
    wait_for_output(session, "gpt-5.4 xhigh")

    status = core.get_session_status(session)
    assert status["agent"]["type"] == "codex"

    core.send_keys(session, "sleepwrite 0.5 first.txt alpha")
    wait_for_output(session, "Working")

    cli_main(["send", "--wait", "--timeout", "3", session, "write second.txt beta"])

    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    wait_for(first.exists, timeout=3.0, message="timed out waiting for first.txt")
    wait_for(second.exists, timeout=3.0, message="timed out waiting for second.txt")
    wait_for(lambda: second.read_text() == "beta\n", timeout=3.0, message="timed out waiting for second.txt contents")

    output = wait_for_output(session, "WROTE second.txt", timeout=3.0)
    assert "WROTE first.txt" in output


def test_cli_send_wait_uses_claude_transcript_state_with_real_tmux(
    real_tmux: RealTmuxServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    session = "mock-claude-send-wait"
    monkeypatch.setenv("CLAUDE_PROJECTS_DIR", str(tmp_path / "claude-projects"))
    launch_mock_claude(session, tmp_path)

    status = core.get_session_status(session)
    assert status["agent"]["type"] == "claude-code"

    core.send_keys(session, "sleepwrite 0.5 first.txt alpha")
    wait_for_output(session, "Running tool...", timeout=3.0)

    cli_main(["send", "--wait", "--timeout", "3", session, "write second.txt beta"])

    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    wait_for(first.exists, timeout=3.0, message="timed out waiting for first.txt")
    wait_for(second.exists, timeout=3.0, message="timed out waiting for second.txt")
    wait_for(lambda: second.read_text() == "beta\n", timeout=3.0, message="timed out waiting for second.txt contents")

    output = wait_for_output(session, "WROTE second.txt", timeout=3.0)
    assert "WROTE first.txt" in output
