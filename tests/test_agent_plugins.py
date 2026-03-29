"""Tests for built-in agent plugins and display integration."""

from __future__ import annotations

from pathlib import Path

from tmux_pilot import agent_sessions, core, display
from tmux_pilot.plugins.agents import claude_code, codex, generic, get_agent_state


def test_claude_code_detects_version_string():
    assert claude_code.detect("2.1.76", "")


def test_claude_code_reports_idle(monkeypatch):
    monkeypatch.setattr(core, "peek_session", lambda session_name, lines=30: "Ready\n❯")

    state = claude_code.get_state("alpha")

    assert state == {"type": "claude-code", "state": "idle", "ready": True}


def test_claude_transcript_running_overrides_idle_pane(monkeypatch):
    monkeypatch.setattr(core, "peek_session", lambda session_name, lines=200: "Claude Code\n\n❯")
    monkeypatch.setattr(
        agent_sessions,
        "get_claude_transcript_state",
        lambda cwd, transcript_path=None: agent_sessions.TranscriptState(
            path=Path("/tmp/claude.jsonl"),
            state="running",
        ),
    )

    state = claude_code.get_state("alpha", working_dir="/tmp/example")

    assert state == {"type": "claude-code", "state": "running", "ready": False}


def test_claude_transcript_completion_requires_prompt_before_ready(monkeypatch):
    monkeypatch.setattr(core, "peek_session", lambda session_name, lines=200: "TaskCompleted")
    monkeypatch.setattr(
        agent_sessions,
        "get_claude_transcript_state",
        lambda cwd, transcript_path=None: agent_sessions.TranscriptState(
            path=Path("/tmp/claude.jsonl"),
            state="completed",
        ),
    )

    state = claude_code.get_state("alpha", working_dir="/tmp/example")

    assert state == {"type": "claude-code", "state": "completed", "ready": False}


def test_claude_transcript_completion_is_ready_once_prompt_returns(monkeypatch):
    pane = "Claude Code\n\n❯"
    monkeypatch.setattr(core, "peek_session", lambda session_name, lines=200: pane)
    monkeypatch.setattr(
        agent_sessions,
        "get_claude_transcript_state",
        lambda cwd, transcript_path=None: agent_sessions.TranscriptState(
            path=Path("/tmp/claude.jsonl"),
            state="completed",
        ),
    )

    state = claude_code.get_state("alpha", working_dir="/tmp/example")

    assert state == {"type": "claude-code", "state": "completed", "ready": True}


def test_codex_reports_completed(monkeypatch):
    monkeypatch.setattr(core, "peek_session", lambda session_name, lines=30: "Task completed successfully")

    state = codex.get_state("alpha")

    assert state == {"type": "codex", "state": "completed", "ready": True}


def test_codex_reports_idle_from_interactive_prompt(monkeypatch):
    pane = """
› Find and fix a bug in @filename

  gpt-5.4 xhigh · 96% left · /tmp/example
"""
    monkeypatch.setattr(core, "peek_session", lambda session_name, lines=30: pane)

    state = codex.get_state("alpha")

    assert state == {"type": "codex", "state": "idle", "ready": True}


def test_codex_reports_running_when_working(monkeypatch):
    pane = """
• Working (12s • esc to interrupt)

› Find and fix a bug in @filename

  gpt-5.4 xhigh · 96% left · /tmp/example
"""
    monkeypatch.setattr(core, "peek_session", lambda session_name, lines=30: pane)

    state = codex.get_state("alpha")

    assert state == {"type": "codex", "state": "running", "ready": False}


def test_codex_does_not_false_complete_on_command_output(monkeypatch):
    pane = """
• The shell sleep completed. Creating busy_first.txt now.

› Find and fix a bug in @filename

  gpt-5.4 xhigh · 95% left · /tmp/example
"""
    monkeypatch.setattr(core, "peek_session", lambda session_name, lines=30: pane)

    state = codex.get_state("alpha")

    assert state == {"type": "codex", "state": "idle", "ready": True}


def test_codex_transcript_running_overrides_idle_pane(monkeypatch):
    pane = """
› Find and fix a bug in @filename

  gpt-5.4 xhigh · 96% left · /tmp/example
"""
    monkeypatch.setattr(core, "peek_session", lambda session_name, lines=30: pane)
    monkeypatch.setattr(
        agent_sessions,
        "get_codex_transcript_state",
        lambda cwd, transcript_path=None: agent_sessions.TranscriptState(
            path=Path("/tmp/mock.jsonl"),
            state="running",
        ),
    )

    state = codex.get_state("alpha", working_dir="/tmp/example")

    assert state == {"type": "codex", "state": "running", "ready": False}


def test_codex_transcript_completion_requires_prompt_before_ready(monkeypatch):
    monkeypatch.setattr(core, "peek_session", lambda session_name, lines=30: "Task completed successfully")
    monkeypatch.setattr(
        agent_sessions,
        "get_codex_transcript_state",
        lambda cwd, transcript_path=None: agent_sessions.TranscriptState(
            path=Path("/tmp/mock.jsonl"),
            state="completed",
        ),
    )

    state = codex.get_state("alpha", working_dir="/tmp/example")

    assert state == {"type": "codex", "state": "completed", "ready": False}


def test_codex_transcript_completion_is_ready_once_prompt_returns(monkeypatch):
    pane = """
› Find and fix a bug in @filename

  gpt-5.4 xhigh · 96% left · /tmp/example
"""
    monkeypatch.setattr(core, "peek_session", lambda session_name, lines=30: pane)
    monkeypatch.setattr(
        agent_sessions,
        "get_codex_transcript_state",
        lambda cwd, transcript_path=None: agent_sessions.TranscriptState(
            path=Path("/tmp/mock.jsonl"),
            state="completed",
        ),
    )

    state = codex.get_state("alpha", working_dir="/tmp/example")

    assert state == {"type": "codex", "state": "completed", "ready": True}


def test_generic_uses_prompt_regex(monkeypatch):
    monkeypatch.setattr(core, "peek_session", lambda session_name, lines=30: "custom agent\n>")

    state = generic.get_state("alpha")

    assert state == {"type": "generic", "state": "idle", "ready": True}


def test_registry_selects_codex_plugin(monkeypatch):
    monkeypatch.setattr(core, "peek_session", lambda session_name, lines=30: "OpenAI Codex\n>")

    state = get_agent_state("alpha", "codex")

    assert state["type"] == "codex"
    assert state["state"] == "idle"
    assert state["ready"] is True


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
