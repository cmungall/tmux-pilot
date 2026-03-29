"""Built-in agent plugin for Codex sessions."""

from __future__ import annotations

import re
from pathlib import Path

from ... import agent_sessions
from ... import core

_STATUS_LINE_RE = re.compile(r"^\s*gpt-[\w.-]+(?:\s+\w+)?\s+·\s+.+$")
_TERMINAL_STATES = {"completed", "interrupted", "error"}


def detect(pane_command: str, pane_output: str) -> bool:
    """Detect Codex from its command name or recent output."""
    command = pane_command.strip().lower()
    return command == "codex" or "codex" in pane_output.lower()


def _last_line(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _nonempty_lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def _looks_idle(lines: list[str]) -> bool:
    if len(lines) < 2:
        return False
    tail = lines[-6:]
    has_prompt = any(line.lstrip().startswith("› ") for line in tail)
    has_status = any(_STATUS_LINE_RE.match(line) for line in tail)
    return has_prompt and has_status


def _state_from_output(pane_output: str) -> str:
    if re.search(r"\b(task completed(?: successfully)?|all done)\b", pane_output, re.IGNORECASE):
        return "completed"
    if re.search(r"\bWorking \(\d+s\b", pane_output, re.IGNORECASE):
        return "running"
    lines = _nonempty_lines(pane_output)
    if _looks_idle(lines):
        return "idle"
    if _last_line(pane_output).endswith(">"):
        return "idle"
    if pane_output.strip():
        return "running"
    return "unknown"


def _looks_ready_for_input(pane_output: str) -> bool:
    markers = ("› ", "gpt-", "@filename")
    return any(marker in pane_output for marker in markers)


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
    """Return Codex state using transcript data first, then pane output."""
    pane_output = pane_output or core.peek_session(session_name, lines=200)
    transcript_state = agent_sessions.get_codex_transcript_state(
        working_dir,
        transcript_path=transcript_path,
    ) if working_dir else None
    state, ready = _merge_states(pane_output, _state_from_output(pane_output), transcript_state)
    return {
        "type": "codex",
        "state": state,
        "ready": ready,
    }
