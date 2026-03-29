#!/usr/bin/env python3
"""Tiny interactive TUI that mimics Claude Code transcript behavior.

The mock keeps a single prompt alive inside tmux and writes a minimal
Claude-style JSONL transcript so tmux-pilot can exercise file-backed watcher
logic without depending on the real Claude Code binary.
"""

from __future__ import annotations

import json
import os
import select
import sys
import termios
import time
import tty
import uuid
from datetime import datetime, timezone
from pathlib import Path


PROMPT_TEXT = "How can I help?"


def _write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class TranscriptWriter:
    def __init__(self, cwd: str) -> None:
        self.path: Path | None = None
        projects_root = os.environ.get("CLAUDE_PROJECTS_DIR")
        if not projects_root:
            return

        session_id = f"mock-{uuid.uuid4()}"
        encoded_cwd = cwd.replace("/", "-") or "-"
        path = Path(projects_root).expanduser() / encoded_cwd / f"{session_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.cwd = cwd
        self.session_id = session_id

    def _emit(self, record_type: str, message: dict[str, object]) -> str:
        if self.path is None:
            return ""

        record_id = str(uuid.uuid4())
        record = {
            "cwd": self.cwd,
            "sessionId": self.session_id,
            "type": record_type,
            "message": message,
            "uuid": record_id,
            "timestamp": _now_iso(),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        return record_id

    def user_message(self, text: str) -> str:
        return self._emit(
            "user",
            {
                "role": "user",
                "content": text,
            },
        )

    def assistant_tool_use(self, command: str) -> str:
        return self._emit(
            "assistant",
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {"command": command},
                    }
                ],
            },
        )

    def assistant_text(self, text: str) -> str:
        return self._emit(
            "assistant",
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": text,
                    }
                ],
            },
        )


def _render_prompt() -> None:
    _write("\nClaude Code mock\n")
    _write(f"{PROMPT_TEXT}\n")
    _write("❯")


def _write_file(path: Path, text: str) -> str:
    path.write_text(text + "\n", encoding="utf-8")
    return f"\nWROTE {path.name}\n"


def _append_file(path: Path, text: str) -> str:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")
    return f"\nAPPENDED {path.name}\n"


def _count_file(path: Path) -> str:
    count = 0
    if path.exists():
        count = len(path.read_text(encoding="utf-8").splitlines())
    return f"\nCOUNT {count}\n"


def _execute_command(command: str) -> tuple[str, tuple[object, ...] | None]:
    parts = command.split()
    if not parts:
        return "", None

    action = parts[0]
    if action == "write" and len(parts) >= 3:
        return _write_file(Path(parts[1]), " ".join(parts[2:])), None
    if action == "append" and len(parts) >= 3:
        return _append_file(Path(parts[1]), " ".join(parts[2:])), None
    if action == "count" and len(parts) == 2:
        return _count_file(Path(parts[1])), None
    if action == "sleepwrite" and len(parts) >= 4:
        return "\nRunning tool...\n", ("write", float(parts[1]), Path(parts[2]), " ".join(parts[3:]))
    if action == "exit":
        return "\nBYE\n", ("exit",)
    return f"\nUNKNOWN {command}\n", None


def main() -> int:
    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)
    tty.setraw(fd)
    try:
        transcript = TranscriptWriter(os.getcwd())
        buffer = ""
        pending_action: tuple[object, ...] | None = None
        pending_command = ""

        _render_prompt()

        while True:
            if pending_action is not None:
                action, ready_at, path, text = pending_action
                timeout = max(0.0, float(ready_at) - time.monotonic())
                ready, _, _ = select.select([fd], [], [], timeout)
                if ready:
                    os.read(fd, 1024)
                    continue

                if action == "write":
                    _write(_write_file(Path(path), str(text)))
                    transcript.assistant_text(f"Completed: {pending_command}")
                pending_action = None
                pending_command = ""
                _render_prompt()
                continue

            raw = os.read(fd, 1)
            if not raw:
                return 0
            char = raw.decode("utf-8", errors="replace")

            if char in "\r\n":
                command = buffer.strip()
                buffer = ""

                if not command:
                    _render_prompt()
                    continue

                transcript.user_message(command)
                output, action = _execute_command(command)
                if action is not None and action[0] == "write":
                    transcript.assistant_tool_use(command)
                    pending_action = (action[0], time.monotonic() + float(action[1]), action[2], action[3])
                    pending_command = command
                    _write(output)
                    continue

                if action is not None and action[0] == "exit":
                    _write(output)
                    return 0

                _write(output)
                transcript.assistant_text(f"Completed: {command}")
                _render_prompt()
                continue

            if char == "\x03":
                return 130

            buffer += char
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original)


if __name__ == "__main__":
    raise SystemExit(main())
