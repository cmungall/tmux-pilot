"""Formatting and table output for tmux-pilot."""

from __future__ import annotations

from .core import SessionInfo


def format_session_table(sessions: list[SessionInfo]) -> str:
    """Format sessions as an aligned table."""
    if not sessions:
        return "No tmux sessions found."

    # Column definitions: (header, accessor)
    columns = [
        ("NAME", lambda s: s.name),
        ("STATUS", lambda s: s.status or "-"),
        ("PROCESS", lambda s: s.process),
        ("DESC", lambda s: s.desc or "-"),
        ("DIR", lambda s: _shorten_path(s.working_dir)),
    ]

    headers = [c[0] for c in columns]
    rows = [[accessor(s) for _, accessor in columns] for s in sessions]

    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    # Format
    lines = []
    header_line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    lines.append(header_line)
    lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))

    return "\n".join(lines)


def format_status(info: dict) -> str:
    """Format detailed session status."""
    lines = [
        f"Session:  {info['name']}",
        f"Process:  {info['process']}",
        f"PID:      {info['pid']}",
        f"Dir:      {info['working_dir']}",
    ]

    meta = info.get("metadata", {})
    if meta:
        lines.append("")
        lines.append("Metadata:")
        for k, v in sorted(meta.items()):
            lines.append(f"  @{k} = {v}")

    scrollback = info.get("scrollback_tail", "")
    if scrollback.strip():
        lines.append("")
        lines.append("Last scrollback:")
        lines.append("─" * 60)
        lines.append(scrollback)
        lines.append("─" * 60)

    return "\n".join(lines)


def _shorten_path(path: str) -> str:
    """Shorten a path for display — replace $HOME with ~."""
    import os

    home = os.path.expanduser("~")
    if path.startswith(home):
        return "~" + path[len(home):]
    return path
