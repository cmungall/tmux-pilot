"""Helpers for file-backed agent session state."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

_TRANSCRIPT_SCAN_LIMIT = 200
_HEAD_SCAN_LINES = 8
_READ_CHUNK_SIZE = 8192
SUPPORTED_AGENT_TYPES = ("codex", "claude-code", "pi")


@dataclass(frozen=True)
class TranscriptState:
    """Latest lifecycle state derived from an agent transcript file."""

    path: Path
    state: str
    timestamp: str = ""
    turn_id: str = ""


def codex_sessions_root() -> Path:
    """Return the Codex sessions directory."""
    codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    return codex_home / "sessions"


def claude_projects_root() -> Path:
    """Return the Claude Code transcript directory."""
    return Path(os.environ.get("CLAUDE_PROJECTS_DIR", "~/.claude/projects")).expanduser()


def pi_sessions_root() -> Path:
    """Return the Pi sessions directory."""
    agent_dir = Path(os.environ.get("PI_CODING_AGENT_DIR", "~/.pi/agent")).expanduser()
    return agent_dir / "sessions"


def is_supported_agent_type(agent_type: str) -> bool:
    """Return True when *agent_type* has transcript support."""
    return agent_type in SUPPORTED_AGENT_TYPES


def _normalize_cwd(cwd: str) -> str:
    if not cwd:
        return ""
    try:
        return str(Path(cwd).expanduser().resolve())
    except OSError:
        return str(Path(cwd).expanduser())


def _load_json_line(line: str) -> dict | None:
    line = line.strip()
    if not line:
        return None
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _extract_cwd(record: dict) -> str:
    cwd = record.get("cwd")
    if isinstance(cwd, str):
        return cwd

    record_type = record.get("type")
    payload = record.get("payload")
    if record_type not in {"session_meta", "turn_context"} or not isinstance(payload, dict):
        return ""
    cwd = payload.get("cwd")
    return cwd if isinstance(cwd, str) else ""


def _recent_jsonl_files(root: Path, *, limit: int = _TRANSCRIPT_SCAN_LIMIT) -> list[Path]:
    if not root.exists():
        return []

    candidates: list[tuple[float, Path]] = []
    for path in root.rglob("*.jsonl"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        candidates.append((mtime, path))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in candidates[:limit]]


def transcript_cwd(path: Path, *, max_lines: int = _HEAD_SCAN_LINES) -> str:
    """Read the transcript cwd from the first few JSONL records."""
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index >= max_lines:
                    break
                record = _load_json_line(line)
                if record is None:
                    continue
                cwd = _extract_cwd(record)
                if cwd:
                    return _normalize_cwd(cwd)
    except OSError:
        return ""
    return ""


def _first_record(path: Path, *, max_lines: int = _HEAD_SCAN_LINES) -> dict | None:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index >= max_lines:
                    break
                record = _load_json_line(line)
                if record is not None:
                    return record
    except OSError:
        return None
    return None


def infer_transcript_agent_type(path: Path) -> str:
    """Infer the owning agent type for a transcript file."""
    record = _first_record(path)
    if record is None:
        return ""

    record_type = record.get("type")
    if record_type == "session_meta":
        return "codex"
    if record_type == "session" and record.get("version") == 3:
        return "pi"
    if record_type in {"user", "assistant"} and isinstance(record.get("sessionId"), str):
        return "claude-code"
    return ""


def find_codex_transcript_for_cwd(
    cwd: str,
    *,
    root: Path | None = None,
    limit: int = _TRANSCRIPT_SCAN_LIMIT,
) -> Path | None:
    """Return the most recent Codex transcript whose cwd matches *cwd*."""
    target = _normalize_cwd(cwd)
    if not target:
        return None

    sessions_root = root or codex_sessions_root()
    for path in _recent_jsonl_files(sessions_root, limit=limit):
        if transcript_cwd(path) == target:
            return path
    return None


def find_claude_transcript_for_cwd(
    cwd: str,
    *,
    root: Path | None = None,
    limit: int = _TRANSCRIPT_SCAN_LIMIT,
) -> Path | None:
    """Return the most recent Claude transcript whose cwd matches *cwd*."""
    target = _normalize_cwd(cwd)
    if not target:
        return None

    projects_root = root or claude_projects_root()
    for path in _recent_jsonl_files(projects_root, limit=limit):
        if transcript_cwd(path) == target:
            return path
    return None


def _pi_encoded_session_dir(cwd: str) -> str:
    normalized = _normalize_cwd(cwd)
    safe = normalized.lstrip("/\\").replace("/", "-").replace("\\", "-").replace(":", "-")
    return f"--{safe}--"


def _pi_candidate_roots(cwd: str, *, root: Path | None = None) -> list[Path]:
    if root is not None:
        return [root]

    target = _normalize_cwd(cwd)
    if not target:
        return [pi_sessions_root()]

    worktree_root = Path(target) / ".tmux-pilot" / "pi" / "sessions"
    default_root = pi_sessions_root() / _pi_encoded_session_dir(target)
    roots = []
    if worktree_root.exists():
        roots.append(worktree_root)
    roots.append(default_root)
    return roots


def find_pi_transcript_for_cwd(
    cwd: str,
    *,
    root: Path | None = None,
    limit: int = _TRANSCRIPT_SCAN_LIMIT,
) -> Path | None:
    """Return the most recent Pi session file whose cwd matches *cwd*."""
    target = _normalize_cwd(cwd)
    if not target:
        return None

    for sessions_root in _pi_candidate_roots(target, root=root):
        for path in _recent_jsonl_files(sessions_root, limit=limit):
            if transcript_cwd(path) == target:
                return path
    return None


def find_transcript_for_cwd(
    agent_type: str,
    cwd: str,
    *,
    limit: int = _TRANSCRIPT_SCAN_LIMIT,
) -> Path | None:
    """Return the latest transcript path for a supported agent session."""
    if agent_type == "codex":
        return find_codex_transcript_for_cwd(cwd, limit=limit)
    if agent_type == "claude-code":
        return find_claude_transcript_for_cwd(cwd, limit=limit)
    if agent_type == "pi":
        return find_pi_transcript_for_cwd(cwd, limit=limit)
    return None


def _iter_lines_reverse(path: Path):
    """Yield file lines from end to start without loading the whole file."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            buffer = b""

            while position > 0:
                read_size = min(_READ_CHUNK_SIZE, position)
                position -= read_size
                handle.seek(position)
                buffer = handle.read(read_size) + buffer
                lines = buffer.splitlines()
                if position > 0:
                    buffer = lines[0]
                    lines = lines[1:]
                else:
                    buffer = b""

                for line in reversed(lines):
                    yield line.decode("utf-8", errors="replace")

            if buffer:
                yield buffer.decode("utf-8", errors="replace")
    except OSError:
        return


def read_codex_transcript_state(path: Path) -> TranscriptState | None:
    """Return the latest Codex lifecycle event from *path*."""
    for line in _iter_lines_reverse(path):
        record = _load_json_line(line)
        if record is None or record.get("type") != "event_msg":
            continue

        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue

        event_type = payload.get("type")
        if not isinstance(event_type, str):
            continue

        timestamp = record.get("timestamp")
        turn_id = payload.get("turn_id")
        if event_type == "task_complete":
            return TranscriptState(
                path=path,
                state="completed",
                timestamp=timestamp if isinstance(timestamp, str) else "",
                turn_id=turn_id if isinstance(turn_id, str) else "",
            )
        if event_type == "task_started":
            return TranscriptState(
                path=path,
                state="running",
                timestamp=timestamp if isinstance(timestamp, str) else "",
                turn_id=turn_id if isinstance(turn_id, str) else "",
            )
        if event_type == "turn_aborted":
            reason = payload.get("reason")
            return TranscriptState(
                path=path,
                state="interrupted" if reason == "interrupted" else "error",
                timestamp=timestamp if isinstance(timestamp, str) else "",
                turn_id=turn_id if isinstance(turn_id, str) else "",
            )
    return None


def _record_timestamp(record: dict) -> str:
    timestamp = record.get("timestamp")
    return timestamp if isinstance(timestamp, str) else ""


def _record_turn_id(record: dict) -> str:
    for key in ("id", "uuid", "turn_id", "sessionId"):
        value = record.get(key)
        if isinstance(value, str):
            return value

    payload = record.get("payload")
    if isinstance(payload, dict):
        value = payload.get("turn_id")
        if isinstance(value, str):
            return value
    return ""


def _claude_assistant_state(record: dict) -> str | None:
    if record.get("type") != "assistant":
        return None

    message = record.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return None

    content = message.get("content")
    if not isinstance(content, list):
        return "completed"
    if any(isinstance(item, dict) and item.get("type") == "tool_use" for item in content):
        return "running"
    return "completed"


def _claude_user_state(record: dict) -> str | None:
    if record.get("type") != "user":
        return None

    message = record.get("message")
    if not isinstance(message, dict) or message.get("role") != "user":
        return None
    return "running"


def read_claude_transcript_state(path: Path) -> TranscriptState | None:
    """Return the latest Claude Code lifecycle state from *path*."""
    for line in _iter_lines_reverse(path):
        record = _load_json_line(line)
        if record is None:
            continue

        state = _claude_assistant_state(record) or _claude_user_state(record)
        if state is None:
            continue

        return TranscriptState(
            path=path,
            state=state,
            timestamp=_record_timestamp(record),
            turn_id=_record_turn_id(record),
        )
    return None


def _pi_message_state(record: dict) -> str | None:
    if record.get("type") != "message":
        return None

    message = record.get("message")
    if not isinstance(message, dict):
        return None

    role = message.get("role")
    if role in {"user", "toolResult", "bashExecution"}:
        return "running"
    if role != "assistant":
        return None

    stop_reason = message.get("stopReason")
    if stop_reason == "toolUse":
        return "running"
    if stop_reason == "aborted":
        return "interrupted"
    if stop_reason == "error":
        return "error"
    return "completed"


def read_pi_transcript_state(path: Path) -> TranscriptState | None:
    """Return the latest Pi lifecycle state from *path*."""
    for line in _iter_lines_reverse(path):
        record = _load_json_line(line)
        if record is None:
            continue

        state = _pi_message_state(record)
        if state is None:
            continue

        return TranscriptState(
            path=path,
            state=state,
            timestamp=_record_timestamp(record),
            turn_id=_record_turn_id(record),
        )
    return None


def get_codex_transcript_state(
    cwd: str,
    *,
    transcript_path: Path | None = None,
    root: Path | None = None,
) -> TranscriptState | None:
    """Resolve and read the latest Codex transcript state for *cwd*."""
    path = transcript_path or find_codex_transcript_for_cwd(cwd, root=root)
    if path is None:
        return None
    return read_codex_transcript_state(path)


def get_claude_transcript_state(
    cwd: str,
    *,
    transcript_path: Path | None = None,
    root: Path | None = None,
) -> TranscriptState | None:
    """Resolve and read the latest Claude Code transcript state for *cwd*."""
    path = transcript_path or find_claude_transcript_for_cwd(cwd, root=root)
    if path is None:
        return None
    return read_claude_transcript_state(path)


def get_pi_transcript_state(
    cwd: str,
    *,
    transcript_path: Path | None = None,
    root: Path | None = None,
) -> TranscriptState | None:
    """Resolve and read the latest Pi session state for *cwd*."""
    path = transcript_path or find_pi_transcript_for_cwd(cwd, root=root)
    if path is None:
        return None
    return read_pi_transcript_state(path)


def read_transcript_state(agent_type: str, path: Path) -> TranscriptState | None:
    """Read transcript state for *agent_type* from *path*."""
    if agent_type == "codex":
        return read_codex_transcript_state(path)
    if agent_type == "claude-code":
        return read_claude_transcript_state(path)
    if agent_type == "pi":
        return read_pi_transcript_state(path)
    return None


def read_transcript_tail(path: Path, *, lines: int = 20) -> list[str]:
    """Return the last *lines* raw JSONL lines from *path*."""
    if lines <= 0:
        return []

    tail: list[str] = []
    for line in _iter_lines_reverse(path):
        tail.append(line)
        if len(tail) >= lines:
            break
    tail.reverse()
    return tail


def read_transcript_records(
    path: Path,
    *,
    limit: int | None = 20,
) -> list[dict]:
    """Return JSON records from *path*, preserving file order.

    When *limit* is provided, returns the last N valid JSON object records.
    When *limit* is None, returns every valid JSON object record in the file.
    """
    records: list[dict] = []
    if limit is not None and limit <= 0:
        return records

    if limit is None:
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    record = _load_json_line(line)
                    if record is not None:
                        records.append(record)
        except OSError:
            return []
        return records

    for line in _iter_lines_reverse(path):
        record = _load_json_line(line)
        if record is None:
            continue
        records.append(record)
        if len(records) >= limit:
            break
    records.reverse()
    return records
