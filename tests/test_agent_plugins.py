"""Tests for built-in agent plugins and display integration."""

from __future__ import annotations

from tmux_pilot import core, display
from tmux_pilot.plugins.agents import claude_code, codex, generic, get_agent_state


def test_claude_code_detects_version_string():
    assert claude_code.detect("2.1.76", "")


def test_claude_code_reports_idle(monkeypatch):
    monkeypatch.setattr(core, "peek_session", lambda session_name, lines=30: "Ready\n❯")

    state = claude_code.get_state("alpha")

    assert state == {"type": "claude-code", "state": "idle"}


def test_codex_reports_completed(monkeypatch):
    monkeypatch.setattr(core, "peek_session", lambda session_name, lines=30: "Task completed successfully")

    state = codex.get_state("alpha")

    assert state == {"type": "codex", "state": "completed"}


def test_generic_uses_prompt_regex(monkeypatch):
    monkeypatch.setattr(core, "peek_session", lambda session_name, lines=30: "custom agent\n>")

    state = generic.get_state("alpha")

    assert state == {"type": "generic", "state": "idle"}


def test_registry_selects_codex_plugin(monkeypatch):
    monkeypatch.setattr(core, "peek_session", lambda session_name, lines=30: "OpenAI Codex\n>")

    state = get_agent_state("alpha", "codex")

    assert state["type"] == "codex"
    assert state["state"] == "idle"


def test_format_session_table_shows_agent_state_column():
    sessions = [
        core.SessionInfo(
            name="alpha",
            process="codex",
            working_dir="/tmp/alpha",
            metadata={"status": "active"},
            agent_state="idle",
        )
    ]

    table = display.format_session_table(sessions)

    assert "AGENT_STATE" in table
    assert "idle" in table


def test_format_status_shows_agent_block():
    rendered = display.format_status(
        {
            "name": "alpha",
            "process": "codex",
            "pid": "123",
            "working_dir": "/tmp/alpha",
            "metadata": {},
            "agent": {"type": "codex", "state": "running"},
        }
    )

    assert "Agent:    codex (running)" in rendered
