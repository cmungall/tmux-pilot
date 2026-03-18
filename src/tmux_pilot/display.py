"""Formatting and table output for tmux-pilot."""

from __future__ import annotations

from .core import SessionInfo

# All available columns: (long_name, mnemonic, accessor)
ALL_COLUMNS: list[tuple[str, str, object]] = [
    ("NAME", "N", lambda s: s.name),
    ("STATUS", "S", lambda s: s.status or "-"),
    ("PROCESS", "P", lambda s: s.process),
    ("DESC", "D", lambda s: s.desc or "-"),
    ("DIR", "W", lambda s: _shorten_path(s.working_dir)),
    ("REPO", "R", lambda s: _shorten_path(s.metadata.get("repo", "")) or "-"),
    ("TASK", "T", lambda s: s.metadata.get("task", "") or "-"),
    ("BRANCH", "B", lambda s: s.metadata.get("branch", "") or "-"),
]

_COL_BY_MNEMONIC = {m: (name, acc) for name, m, acc in ALL_COLUMNS}
_COL_BY_NAME = {name: (name, acc) for name, _, acc in ALL_COLUMNS}

DEFAULT_COLS = "NSPDW"


def parse_cols(spec: str | None) -> list[tuple[str, object]]:
    """Parse a --cols spec into a list of (header, accessor) tuples.

    Accepts either single-letter mnemonics (e.g. "NSP") or
    comma-separated long names (e.g. "NAME,STATUS,PROCESS").
    """
    if not spec:
        spec = DEFAULT_COLS

    # Comma-separated long names
    if "," in spec:
        result = []
        for token in spec.split(","):
            token = token.strip().upper()
            if token in _COL_BY_NAME:
                result.append(_COL_BY_NAME[token])
            else:
                raise ValueError(f"Unknown column: {token}. Available: {', '.join(_COL_BY_NAME)}")
        return result

    # Single-letter mnemonics
    spec = spec.upper()
    result = []
    for ch in spec:
        if ch in _COL_BY_MNEMONIC:
            result.append(_COL_BY_MNEMONIC[ch])
        else:
            valid = ", ".join(f"{m}={n}" for n, m, _ in ALL_COLUMNS)
            raise ValueError(f"Unknown column mnemonic: {ch}. Available: {valid}")
    return result


def format_session_table(sessions: list[SessionInfo], cols: str | None = None) -> str:
    """Format sessions as an aligned table with configurable columns."""
    if not sessions:
        return "No tmux sessions found."

    columns = parse_cols(cols)
    headers = [name for name, _ in columns]
    accessors = [acc for _, acc in columns]
    rows = [[acc(s) for acc in accessors] for s in sessions]

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
