"""Tests for transcript-backed agent session helpers."""

from __future__ import annotations

import os
from pathlib import Path

from tmux_pilot import agent_sessions


def _write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")


def test_transcript_cwd_reads_session_meta(tmp_path: Path):
    transcript = tmp_path / "sessions" / "2026" / "03" / "29" / "rollout.jsonl"
    _write(
        transcript,
        [
            '{"timestamp":"2026-03-29T20:00:00Z","type":"session_meta","payload":{"cwd":"/tmp/project"}}\n',
            '{"timestamp":"2026-03-29T20:00:01Z","type":"event_msg","payload":{"type":"task_started","turn_id":"turn-1"}}\n',
        ],
    )

    assert agent_sessions.transcript_cwd(transcript) == str(Path("/tmp/project").resolve())


def test_transcript_cwd_reads_claude_top_level_cwd(tmp_path: Path):
    transcript = tmp_path / "projects" / "-tmp-project" / "session.jsonl"
    _write(
        transcript,
        [
            '{"cwd":"/tmp/project","sessionId":"claude-1","type":"user","message":{"role":"user","content":"hello"},"uuid":"msg-1","timestamp":"2026-03-29T20:00:00Z"}\n',
        ],
    )

    assert agent_sessions.transcript_cwd(transcript) == str(Path("/tmp/project").resolve())


def test_find_codex_transcript_for_cwd_prefers_most_recent_match(tmp_path: Path):
    root = tmp_path / "sessions"
    older = root / "2026" / "03" / "28" / "older.jsonl"
    newer = root / "2026" / "03" / "29" / "newer.jsonl"
    other = root / "2026" / "03" / "29" / "other.jsonl"
    _write(older, ['{"type":"session_meta","payload":{"cwd":"/tmp/project"}}\n'])
    _write(newer, ['{"type":"session_meta","payload":{"cwd":"/tmp/project"}}\n'])
    _write(other, ['{"type":"session_meta","payload":{"cwd":"/tmp/other"}}\n'])

    os.utime(older, (100, 100))
    os.utime(newer, (200, 200))
    os.utime(other, (150, 150))

    found = agent_sessions.find_codex_transcript_for_cwd("/tmp/project", root=root)

    assert found == newer


def test_infer_transcript_agent_type_detects_codex(tmp_path: Path):
    transcript = tmp_path / "sessions" / "rollout.jsonl"
    _write(
        transcript,
        ['{"timestamp":"2026-03-29T20:00:00Z","type":"session_meta","payload":{"cwd":"/tmp/project"}}\n'],
    )

    assert agent_sessions.infer_transcript_agent_type(transcript) == "codex"


def test_find_claude_transcript_for_cwd_prefers_most_recent_match(tmp_path: Path):
    root = tmp_path / "projects"
    older = root / "-tmp-project" / "older.jsonl"
    newer = root / "-tmp-project" / "newer.jsonl"
    other = root / "-tmp-other" / "other.jsonl"
    _write(older, ['{"cwd":"/tmp/project","type":"user","message":{"role":"user","content":"one"}}\n'])
    _write(newer, ['{"cwd":"/tmp/project","type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"done"}]}}\n'])
    _write(other, ['{"cwd":"/tmp/other","type":"user","message":{"role":"user","content":"other"}}\n'])

    os.utime(older, (100, 100))
    os.utime(newer, (200, 200))
    os.utime(other, (150, 150))

    found = agent_sessions.find_claude_transcript_for_cwd("/tmp/project", root=root)

    assert found == newer


def test_read_codex_transcript_state_reports_running_from_latest_lifecycle_event(tmp_path: Path):
    transcript = tmp_path / "sessions" / "rollout.jsonl"
    _write(
        transcript,
        [
            '{"timestamp":"2026-03-29T20:00:00Z","type":"session_meta","payload":{"cwd":"/tmp/project"}}\n',
            '{"timestamp":"2026-03-29T20:00:01Z","type":"event_msg","payload":{"type":"task_complete","turn_id":"turn-1"}}\n',
            '{"timestamp":"2026-03-29T20:00:02Z","type":"event_msg","payload":{"type":"task_started","turn_id":"turn-2"}}\n',
            '{"timestamp":"2026-03-29T20:00:03Z","type":"response_item","payload":{"type":"message"}}\n',
        ],
    )

    state = agent_sessions.read_codex_transcript_state(transcript)

    assert state == agent_sessions.TranscriptState(
        path=transcript,
        state="running",
        timestamp="2026-03-29T20:00:02Z",
        turn_id="turn-2",
    )


def test_read_codex_transcript_state_reports_interrupted(tmp_path: Path):
    transcript = tmp_path / "sessions" / "rollout.jsonl"
    _write(
        transcript,
        [
            '{"timestamp":"2026-03-29T20:00:00Z","type":"session_meta","payload":{"cwd":"/tmp/project"}}\n',
            '{"timestamp":"2026-03-29T20:00:01Z","type":"event_msg","payload":{"type":"turn_aborted","reason":"interrupted","turn_id":"turn-7"}}\n',
        ],
    )

    state = agent_sessions.read_codex_transcript_state(transcript)

    assert state == agent_sessions.TranscriptState(
        path=transcript,
        state="interrupted",
        timestamp="2026-03-29T20:00:01Z",
        turn_id="turn-7",
    )


def test_read_claude_transcript_state_reports_running_from_tool_use(tmp_path: Path):
    transcript = tmp_path / "projects" / "-tmp-project" / "session.jsonl"
    _write(
        transcript,
        [
            '{"cwd":"/tmp/project","sessionId":"claude-1","type":"user","message":{"role":"user","content":"write a file"},"uuid":"msg-1","timestamp":"2026-03-29T20:00:00Z"}\n',
            '{"cwd":"/tmp/project","sessionId":"claude-1","type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash"}]},"uuid":"msg-2","timestamp":"2026-03-29T20:00:02Z"}\n',
        ],
    )

    state = agent_sessions.read_claude_transcript_state(transcript)

    assert state == agent_sessions.TranscriptState(
        path=transcript,
        state="running",
        timestamp="2026-03-29T20:00:02Z",
        turn_id="msg-2",
    )


def test_read_claude_transcript_state_reports_completed_from_assistant_text(tmp_path: Path):
    transcript = tmp_path / "projects" / "-tmp-project" / "session.jsonl"
    _write(
        transcript,
        [
            '{"cwd":"/tmp/project","sessionId":"claude-1","type":"user","message":{"role":"user","content":"write a file"},"uuid":"msg-1","timestamp":"2026-03-29T20:00:00Z"}\n',
            '{"cwd":"/tmp/project","sessionId":"claude-1","type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"done"}]},"uuid":"msg-3","timestamp":"2026-03-29T20:00:03Z"}\n',
        ],
    )

    state = agent_sessions.read_claude_transcript_state(transcript)

    assert state == agent_sessions.TranscriptState(
        path=transcript,
        state="completed",
        timestamp="2026-03-29T20:00:03Z",
        turn_id="msg-3",
    )


def test_get_codex_transcript_state_resolves_path_from_cwd(tmp_path: Path):
    root = tmp_path / "sessions"
    transcript = root / "2026" / "03" / "29" / "rollout.jsonl"
    _write(
        transcript,
        [
            '{"timestamp":"2026-03-29T20:00:00Z","type":"session_meta","payload":{"cwd":"/tmp/project"}}\n',
            '{"timestamp":"2026-03-29T20:00:01Z","type":"event_msg","payload":{"type":"task_complete","turn_id":"turn-3"}}\n',
        ],
    )

    state = agent_sessions.get_codex_transcript_state("/tmp/project", root=root)

    assert state == agent_sessions.TranscriptState(
        path=transcript,
        state="completed",
        timestamp="2026-03-29T20:00:01Z",
        turn_id="turn-3",
    )


def test_get_claude_transcript_state_resolves_path_from_cwd(tmp_path: Path):
    root = tmp_path / "projects"
    transcript = root / "-tmp-project" / "session.jsonl"
    _write(
        transcript,
        [
            '{"cwd":"/tmp/project","sessionId":"claude-1","type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"done"}]},"uuid":"msg-9","timestamp":"2026-03-29T20:00:09Z"}\n',
        ],
    )

    state = agent_sessions.get_claude_transcript_state("/tmp/project", root=root)

    assert state == agent_sessions.TranscriptState(
        path=transcript,
        state="completed",
        timestamp="2026-03-29T20:00:09Z",
        turn_id="msg-9",
    )


def test_find_pi_transcript_for_cwd_uses_worktree_session_dir(tmp_path: Path):
    worktree = tmp_path / "worktree"
    session_dir = worktree / ".tmux-pilot" / "pi" / "sessions"
    transcript = session_dir / "session.jsonl"
    _write(
        transcript,
        [
            f'{{"type":"session","version":3,"id":"pi-1","timestamp":"2026-03-29T20:00:00Z","cwd":"{worktree}"}}\n',
            '{"type":"message","id":"msg-1","parentId":null,"timestamp":"2026-03-29T20:00:01Z","message":{"role":"assistant","content":[{"type":"text","text":"done"}],"stopReason":"stop"}}\n',
        ],
    )

    found = agent_sessions.find_pi_transcript_for_cwd(str(worktree))

    assert found == transcript


def test_read_pi_transcript_state_reports_running_from_tool_use(tmp_path: Path):
    transcript = tmp_path / "sessions" / "pi.jsonl"
    _write(
        transcript,
        [
            '{"type":"session","version":3,"id":"pi-1","timestamp":"2026-03-29T20:00:00Z","cwd":"/tmp/project"}\n',
            '{"type":"message","id":"msg-1","parentId":null,"timestamp":"2026-03-29T20:00:01Z","message":{"role":"assistant","content":[{"type":"toolCall","name":"bash","id":"tool-1","arguments":{"command":"pwd"}}],"stopReason":"toolUse"}}\n',
        ],
    )

    state = agent_sessions.read_pi_transcript_state(transcript)

    assert state == agent_sessions.TranscriptState(
        path=transcript,
        state="running",
        timestamp="2026-03-29T20:00:01Z",
        turn_id="msg-1",
    )


def test_read_pi_transcript_state_reports_completed_from_assistant_stop(tmp_path: Path):
    transcript = tmp_path / "sessions" / "pi.jsonl"
    _write(
        transcript,
        [
            '{"type":"session","version":3,"id":"pi-1","timestamp":"2026-03-29T20:00:00Z","cwd":"/tmp/project"}\n',
            '{"type":"message","id":"msg-2","parentId":null,"timestamp":"2026-03-29T20:00:03Z","message":{"role":"assistant","content":[{"type":"text","text":"done"}],"stopReason":"stop"}}\n',
        ],
    )

    state = agent_sessions.read_pi_transcript_state(transcript)

    assert state == agent_sessions.TranscriptState(
        path=transcript,
        state="completed",
        timestamp="2026-03-29T20:00:03Z",
        turn_id="msg-2",
    )


def test_read_transcript_tail_returns_latest_lines(tmp_path: Path):
    transcript = tmp_path / "sessions" / "rollout.jsonl"
    _write(
        transcript,
        [
            '{"line":1}\n',
            '{"line":2}\n',
            '{"line":3}\n',
        ],
    )

    assert agent_sessions.read_transcript_tail(transcript, lines=2) == ['{"line":2}', '{"line":3}']


def test_read_transcript_records_reads_latest_claude_records(tmp_path: Path):
    transcript = tmp_path / "projects" / "-tmp-project" / "session.jsonl"
    _write(
        transcript,
        [
            '{"cwd":"/tmp/project","sessionId":"claude-1","type":"user","message":{"role":"user","content":"hello"},"uuid":"msg-1","timestamp":"2026-03-29T20:00:00Z"}\n',
            '{"cwd":"/tmp/project","sessionId":"claude-1","type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"done"}]},"uuid":"msg-2","timestamp":"2026-03-29T20:00:01Z"}\n',
        ],
    )

    records = agent_sessions.read_transcript_records(transcript, limit=1)

    assert records == [
        {
            "cwd": "/tmp/project",
            "sessionId": "claude-1",
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
            "uuid": "msg-2",
            "timestamp": "2026-03-29T20:00:01Z",
        }
    ]
