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


def wait_for_mock_codex_prompt(session_name: str, *, timeout: float = 3.0) -> str:
    """Accept the trust prompt and wait until the normal Codex prompt is ready."""
    output = ""

    def has_prompt() -> bool:
        nonlocal output
        output = core.peek_session(session_name, lines=200)
        # Narrow tmux panes can soft-wrap the status line, splitting "gpt-5.4"
        # across lines in capture-pane output.
        if "gpt-5.4xhigh" in "".join(output.split()):
            return True
        if "Press enter" in output:
            core.send_keys(session_name, "1")
        return False

    try:
        wait_for(has_prompt, timeout=timeout, message="timed out waiting for mock Codex prompt")
    except AssertionError as exc:
        raise AssertionError(f"{exc}\nLast tmux output:\n{output}") from exc
    return output


def launch_mock_claude(session_name: str, workdir: Path) -> None:
    command = f"{shlex.quote(sys.executable)} -u {shlex.quote(str(MOCK_CLAUDE))}"
    core._run(
        ["tmux", "new-session", "-d", "-s", session_name, "-c", str(workdir), command],
        check=True,
    )
    wait_for_output(session_name, "Claude Code mock")


def launch_real_pi(session_name: str, workdir: Path, session_dir: Path) -> None:
    if shutil.which("pi") is None:
        pytest.skip("pi is required for Pi integration tests")

    command = " ".join(
        [
            "PI_OFFLINE=1",
            "pi",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-themes",
            "--session-dir",
            shlex.quote(str(session_dir)),
        ]
    )
    core._run(
        ["tmux", "new-session", "-d", "-s", session_name, "-c", str(workdir), command],
        check=True,
    )
    wait_for_output(session_name, "pi v", timeout=8.0)


def init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "tmux-pilot"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "tmux-pilot@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True, text=True)


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

    wait_for_mock_codex_prompt(session)

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


def test_get_session_status_detects_real_pi(real_tmux: RealTmuxServer, tmp_path: Path):
    session = "real-pi-status"
    launch_real_pi(session, tmp_path, tmp_path / "pi-sessions")

    status = core.get_session_status(session)

    assert status["process"] == "pi"
    assert status["agent"]["type"] == "pi"
    assert status["agent"]["ready"] is True


def test_cli_new_bootstraps_worktree_and_launches_real_pi(
    real_tmux: RealTmuxServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    if shutil.which("pi") is None:
        pytest.skip("pi is required for Pi integration tests")

    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    config = tmp_path / "profiles.toml"
    worktrees = tmp_path / "worktrees"
    config.write_text(
        f"""
[profiles.pi]
worktree_base = "{worktrees}"
branch_prefix = "task"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(core, "PROFILE_CONFIG_PATH", config)

    session = "pi-task"
    cli_main(["new", session, "--profile", "pi", "--repo", str(repo)])

    expected_worktree = worktrees / f"{repo.name}-{session}"
    wait_for_output(session, "pi v", timeout=8.0)

    status = core.get_session_status(session)

    assert status["working_dir"] == str(expected_worktree)
    assert status["process"] == "pi"
    assert status["agent"]["type"] == "pi"
    assert status["metadata"]["branch"] == "task/pi-task"
    assert subprocess.run(
        ["git", "-C", str(expected_worktree), "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == "task/pi-task"

    core.send_keys(session, "/name tmux-pilot-pi")
    wait_for_output(session, "Session name set: tmux-pilot-pi", timeout=5.0)
