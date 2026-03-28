"""Built-in agent plugin registry."""

from __future__ import annotations

from . import claude_code, codex, generic
from ... import core

_PLUGINS = (claude_code, codex, generic)


def get_agent_state(session_name: str, pane_command: str) -> dict[str, str]:
    """Return state from the first matching built-in agent plugin."""
    pane_output = core.peek_session(session_name, lines=30)
    for plugin in _PLUGINS:
        if plugin.detect(pane_command, pane_output):
            return plugin.get_state(session_name)
    return generic.get_state(session_name)
