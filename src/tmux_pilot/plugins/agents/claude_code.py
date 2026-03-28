"""Built-in agent plugin for Claude Code sessions."""

from __future__ import annotations

import re

from ... import core

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


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


def _state_from_output(pane_output: str) -> str:
    if re.search(r"\b(TaskCompleted|Stop)\b", pane_output):
        return "completed"
    if _last_line(pane_output).endswith("❯"):
        return "idle"
    if pane_output.strip():
        return "running"
    return "unknown"


def get_state(session_name: str) -> dict[str, str]:
    """Return Claude Code state derived from recent pane output."""
    pane_output = core.peek_session(session_name, lines=30)
    return {
        "type": "claude-code",
        "state": _state_from_output(pane_output),
    }
