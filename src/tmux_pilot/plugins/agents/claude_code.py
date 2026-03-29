"""Built-in agent plugin for Claude Code sessions."""

from __future__ import annotations

import re
from pathlib import Path

from ... import agent_sessions
from ... import core

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_TERMINAL_STATES = {"completed", "interrupted", "error"}


def detect(pane_command: str, pane_output: str) -> bool:
    """Detect Claude Code from its command name, version string, or output."""
    command = pane_command.strip().lower()
    output = pane_output.lower()
    return (
        command in {"claude", "claude-code"}
        or bool(_VERSION_RE.match(pane_command.strip()))
        or "claude code" in output
    )


def _last_line(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _nonempty_lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def _looks_ready_for_input(pane_output: str) -> bool:
    tail = _nonempty_lines(pane_output)[-4:]
    return any(line.endswith("❯") or line.lstrip().startswith("❯") for line in tail)


def _state_from_output(pane_output: str) -> str:
    if re.search(r"\b(TaskCompleted|Stop)\b", pane_output):
        return "completed"
    if _looks_ready_for_input(pane_output) or _last_line(pane_output).endswith("❯"):
        return "idle"
    if pane_output.strip():
        return "running"
    return "unknown"


def _merge_states(
    pane_output: str,
    pane_state: str,
    transcript_state: agent_sessions.TranscriptState | None,
) -> tuple[str, bool]:
    if transcript_state is None:
        return pane_state, pane_state in {"idle", "completed"}

    if transcript_state.state == "running":
        return "running", False

    if transcript_state.state in _TERMINAL_STATES:
        return transcript_state.state, pane_state == "idle" or _looks_ready_for_input(pane_output)

    return pane_state, pane_state in {"idle", "completed"}


def get_state(
    session_name: str,
    pane_output: str | None = None,
    *,
    working_dir: str = "",
    transcript_path: Path | None = None,
) -> dict[str, str | bool]:
    """Return Claude Code state using transcript data first, then pane output."""
    pane_output = pane_output or core.peek_session(session_name, lines=200)
    transcript_state = agent_sessions.get_claude_transcript_state(
        working_dir,
        transcript_path=transcript_path,
    ) if working_dir else None
    state, ready = _merge_states(pane_output, _state_from_output(pane_output), transcript_state)
    return {
        "type": "claude-code",
        "state": state,
        "ready": ready,
    }
