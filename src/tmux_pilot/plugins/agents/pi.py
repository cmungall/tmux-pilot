"""Built-in agent plugin for Pi sessions."""

from __future__ import annotations

import re
from pathlib import Path

from ... import agent_sessions
from ... import core

_TERMINAL_STATES = {"completed", "interrupted", "error"}
_FOOTER_RE = re.compile(
    r"\([a-z0-9_.-]+\)\s+[a-z0-9_.-]+(?:\s+•\s+(?:thinking off|off|minimal|low|medium|high|xhigh))?$",
    re.IGNORECASE,
)


def detect(pane_command: str, pane_output: str) -> bool:
    """Detect Pi from its command name or startup/banner text."""
    command = pane_command.strip().lower()
    output = pane_output.lower()
    return (
        command == "pi"
        or bool(re.search(r"\bpi v\d+\.\d+\.\d+\b", output))
        or "/ for commands" in output
    )


def _nonempty_lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def _looks_ready_for_input(pane_output: str) -> bool:
    lines = _nonempty_lines(pane_output)
    if any(line.strip() == "/ for commands" for line in lines):
        return True
    return any(_FOOTER_RE.search(line.strip()) for line in lines[-4:])


def _state_from_output(pane_output: str) -> str:
    if not pane_output.strip():
        return "unknown"
    if _looks_ready_for_input(pane_output):
        return "idle"
    return "running"


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
        return transcript_state.state, _looks_ready_for_input(pane_output)

    return pane_state, pane_state in {"idle", "completed"}


def get_state(
    session_name: str,
    pane_output: str | None = None,
    *,
    working_dir: str = "",
    transcript_path: Path | None = None,
) -> dict[str, str | bool]:
    """Return Pi state using session transcripts when available."""
    pane_output = pane_output or core.peek_session(session_name, lines=200)
    transcript_state = agent_sessions.get_pi_transcript_state(
        working_dir,
        transcript_path=transcript_path,
    ) if working_dir else None
    state, ready = _merge_states(pane_output, _state_from_output(pane_output), transcript_state)
    return {
        "type": "pi",
        "state": state,
        "ready": ready,
    }
