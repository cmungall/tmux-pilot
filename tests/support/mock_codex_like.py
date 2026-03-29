#!/usr/bin/env python3
"""Tiny interactive TUI that mimics Codex prompt and transcript behavior.

The mock intentionally ignores Enter if it arrives too quickly after the last
typed character. When ``CODEX_HOME`` is set it also writes a minimal Codex-like
JSONL transcript so tmux-pilot can exercise file-backed watcher logic without
depending on the real Codex binary.
"""

from __future__ import annotations

import json
import os
import select
import sys
import termios
import time
import tty
from datetime import datetime, timezone
from pathlib import Path


SETTLE_SECONDS = 0.08
PROMPT_TEXT = "Find and fix a bug in @filename"
MODEL_STATUS = "gpt-5.4 xhigh · 96% left"


def _write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class TranscriptWriter:
    def __init__(self, cwd: str) -> None:
        self.path: Path | None = None
        codex_home = os.environ.get("CODEX_HOME")
        if not codex_home:
            return

        stamp = datetime.now(timezone.utc)
        path = (
            Path(codex_home).expanduser()
            / "sessions"
            / stamp.strftime("%Y")
            / stamp.strftime("%m")
            / stamp.strftime("%d")
            / f"rollout-mock-{stamp.strftime('%Y-%m-%dT%H-%M-%S')}-{os.getpid()}.jsonl"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._emit(
            "session_meta",
            {
                "cwd": cwd,
                "originator": "mock_codex_like",
            },
        )

    def _emit(self, record_type: str, payload: dict[str, object]) -> None:
        if self.path is None:
            return
        record = {"timestamp": _now_iso(), "type": record_type, "payload": payload}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def task_started(self, turn_id: str) -> None:
        self._emit("event_msg", {"type": "task_started", "turn_id": turn_id})

    def task_complete(self, turn_id: str) -> None:
        self._emit("event_msg", {"type": "task_complete", "turn_id": turn_id})


def _render_prompt(cwd: str) -> None:
    _write(f"\n› {PROMPT_TEXT}\n\n")
    _write(f"  {MODEL_STATUS} · {cwd}\n")


def _write_file(path: Path, text: str) -> str:
    path.write_text(text + "\n")
    return f"\nWROTE {path.name}\n"


def _append_file(path: Path, text: str) -> str:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")
    return f"\nAPPENDED {path.name}\n"


def _count_file(path: Path) -> str:
    count = 0
    if path.exists():
        count = len(path.read_text().splitlines())
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
        return "\n• Working (0s • esc to interrupt)\n", ("write", float(parts[1]), Path(parts[2]), " ".join(parts[3:]))

    if action == "exit":
        return "\nBYE\n", ("exit",)

    return f"\nUNKNOWN {command}\n", None


def main() -> int:
    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)
    tty.setraw(fd)
    try:
        cwd = os.getcwd()
        transcript = TranscriptWriter(cwd)
        _write("OpenAI Codex mock\n\n")
        _write(f"> You are in {cwd}\n\n")
        _write("Do you trust the contents of this directory?\n\n")
        _write("› 1. Yes, continue\n")
        _write("  2. No, quit\n\n")
        _write("  Press enter to continue\n")

        trusted = False
        buffer = ""
        last_text_at = 0.0
        turn_index = 0
        pending_action: tuple[object, ...] | None = None
        pending_turn_id = ""

        while True:
            if pending_action is not None:
                action, duration, path, text = pending_action
                timeout = max(0.0, float(duration) - time.monotonic())
                ready, _, _ = select.select([fd], [], [], timeout)
                if ready:
                    os.read(fd, 1024)
                    continue

                if action == "write":
                    _write(_write_file(Path(path), str(text)))
                transcript.task_complete(pending_turn_id)
                pending_action = None
                pending_turn_id = ""
                _render_prompt(cwd)
                continue

            raw = os.read(fd, 1)
            if not raw:
                return 0
            char = raw.decode("utf-8", errors="replace")

            if char in "\r\n":
                if buffer and (time.monotonic() - last_text_at) < SETTLE_SECONDS:
                    continue

                command = buffer.strip()
                buffer = ""

                if not trusted:
                    if command == "1":
                        trusted = True
                        _write("\nTRUSTED\n")
                        _render_prompt(cwd)
                        continue
                    if command == "2":
                        _write("\nQUIT\n")
                        return 0
                    _write("\nINVALID\n")
                    _render_prompt(cwd)
                    continue

                if not command:
                    _render_prompt(cwd)
                    continue

                turn_index += 1
                turn_id = f"turn-{turn_index}"
                transcript.task_started(turn_id)
                output, action = _execute_command(command)
                _write(output)

                if action is not None and action[0] == "exit":
                    return 0
                if action is not None and action[0] == "write":
                    pending_action = (action[0], time.monotonic() + float(action[1]), action[2], action[3])
                    pending_turn_id = turn_id
                    continue

                transcript.task_complete(turn_id)
                if output != "\nBYE\n":
                    _render_prompt(cwd)
                continue

            if char == "\x03":
                return 130

            buffer += char
            last_text_at = time.monotonic()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original)


if __name__ == "__main__":
    raise SystemExit(main())
