"""Fallback agent plugin using configurable regexes."""

from __future__ import annotations

import os
import re

from ... import core

_DEFAULT_IDLE_RE = r"(?:❯|>)\s*$"
_DEFAULT_DONE_RE = r"\b(done|complete|completed)\b"


def _env_regex(name: str, default: str) -> re.Pattern[str]:
    return re.compile(os.environ.get(name, default), re.IGNORECASE)


def detect(pane_command: str, pane_output: str) -> bool:
    """Fallback detector, optionally narrowed by an environment regex."""
    pattern = os.environ.get("TMUX_PILOT_GENERIC_AGENT_REGEX", "")
    if not pattern:
        return True
    matcher = re.compile(pattern, re.IGNORECASE)
    return bool(matcher.search(pane_command) or matcher.search(pane_output))


def _last_line(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _state_from_output(pane_output: str) -> str:
    if _env_regex("TMUX_PILOT_GENERIC_DONE_REGEX", _DEFAULT_DONE_RE).search(pane_output):
        return "completed"
    if _env_regex("TMUX_PILOT_GENERIC_IDLE_REGEX", _DEFAULT_IDLE_RE).search(_last_line(pane_output)):
        return "idle"
    if pane_output.strip():
        return "running"
    return "unknown"


def get_state(
    session_name: str,
    pane_output: str | None = None,
    *,
    working_dir: str = "",
    transcript_path=None,
) -> dict[str, str | bool]:
    """Return fallback agent state using configurable prompt/completion regexes."""
    del working_dir, transcript_path
    pane_output = pane_output or core.peek_session(session_name, lines=30)
    state = _state_from_output(pane_output)
    return {
        "type": "generic",
        "state": state,
        "ready": state in {"idle", "completed"},
    }
