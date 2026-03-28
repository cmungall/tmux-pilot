"""Built-in agent plugin for Codex sessions."""

from __future__ import annotations

import re

from ... import core


def detect(pane_command: str, pane_output: str) -> bool:
    """Detect Codex from its command name or recent output."""
    command = pane_command.strip().lower()
    return command == "codex" or "codex" in pane_output.lower()


def _last_line(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _state_from_output(pane_output: str) -> str:
    if re.search(r"\b(task completed|all done|completed)\b", pane_output, re.IGNORECASE):
        return "completed"
    if _last_line(pane_output).endswith(">"):
        return "idle"
    if pane_output.strip():
        return "running"
    return "unknown"


def get_state(session_name: str) -> dict[str, str]:
    """Return Codex state derived from recent pane output."""
    pane_output = core.peek_session(session_name, lines=30)
    return {
        "type": "codex",
        "state": _state_from_output(pane_output),
    }
