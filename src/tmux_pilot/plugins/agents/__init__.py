"""Built-in agent plugin registry."""

from __future__ import annotations

from pathlib import Path

from . import claude_code, codex, generic, pi
from ... import core

_PLUGINS = (claude_code, codex, pi, generic)


def get_agent_state(
    session_name: str,
    pane_command: str,
    pane_output: str | None = None,
    *,
    working_dir: str = "",
    transcript_path: Path | None = None,
) -> dict[str, str | bool]:
    """Return state from the first matching built-in agent plugin.

    If *pane_output* is provided it is reused for both detection and state
    inference, avoiding a second ``tmux capture-pane`` call.
    """
    if pane_output is None:
        pane_output = core.peek_session(session_name, lines=200)
    for plugin in _PLUGINS:
        if plugin.detect(pane_command, pane_output):
            return plugin.get_state(
                session_name,
                pane_output=pane_output,
                working_dir=working_dir,
                transcript_path=transcript_path,
            )
    return generic.get_state(
        session_name,
        pane_output=pane_output,
        working_dir=working_dir,
        transcript_path=transcript_path,
    )
