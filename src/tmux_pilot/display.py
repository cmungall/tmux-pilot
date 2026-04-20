"""Formatting and table output for tmux-pilot."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from .core import SessionInfo

ColumnAccessor = Callable[[SessionInfo], str]
_PR_REFRESH_KEYS = {"pr", "pr_state", "pr_review", "pr_merge_state"}
_ALL_METADATA_COLUMN_NAMES = [
    "STATUS",
    "DESC",
    "REPO",
    "TASK",
    "BRANCH",
    "ORIGIN",
    "NEEDS",
    "LAST_COMMIT",
    "LAST_SEND",
    "PR_NUM",
    "PR_STATE",
    "REVIEW",
    "MERGE_STATE",
    "LAST_REFRESH",
    "PUSHING",
]

# All available columns: (long_name, mnemonic, accessor)
ALL_COLUMNS: list[tuple[str, str, ColumnAccessor]] = [
    ("NAME", "N", lambda s: s.name),
    ("STATUS", "S", lambda s: s.status or "-"),
    ("PROCESS", "P", lambda s: s.process),
    ("AGENT_STATE", "A", lambda s: s.agent_state or "-"),
    ("DESC", "D", lambda s: s.desc or "-"),
    ("DIR", "W", lambda s: _shorten_path(s.working_dir)),
    ("REPO", "R", lambda s: _shorten_path(s.metadata.get("repo", "")) or "-"),
    ("TASK", "T", lambda s: s.metadata.get("task", "") or "-"),
    ("BRANCH", "B", lambda s: s.metadata.get("branch", "") or "-"),
    ("PR", "G", lambda s: _pr_summary(s.metadata)),
    ("PR_NUM", "J", lambda s: s.metadata.get("pr", "") or "-"),
    ("PR_STATE", "X", lambda s: s.metadata.get("pr_state", "") or "-"),
    ("REVIEW", "V", lambda s: s.metadata.get("pr_review", "") or "-"),
    ("MERGE_STATE", "M", lambda s: s.metadata.get("pr_merge_state", "") or "-"),
    ("ORIGIN", "O", lambda s: s.metadata.get("origin", "") or "-"),
    ("NEEDS", "E", lambda s: s.metadata.get("needs", "") or "-"),
    ("LAST_COMMIT", "K", lambda s: s.metadata.get("last_commit", "") or "-"),
    ("LAST_SEND", "L", lambda s: s.metadata.get("last_send", "") or "-"),
    ("LAST_REFRESH", "F", lambda s: s.metadata.get("last_refresh", "") or "-"),
    ("PUSHING", "U", lambda s: s.metadata.get("pushing", "") or "-"),
]

_COL_BY_MNEMONIC = {m: (name, acc) for name, m, acc in ALL_COLUMNS}
_COL_BY_NAME = {name: (name, acc) for name, _, acc in ALL_COLUMNS}

DEFAULT_COLS = "NAME,STATUS,PROCESS,AGENT_STATE,PR,DIR"


def parse_cols(spec: str | None) -> list[tuple[str, ColumnAccessor]]:
    """Parse a --cols spec into a list of (header, accessor) tuples.

    Accepts either single-letter mnemonics (e.g. "NSP") or
    comma-separated long names (e.g. "NAME,STATUS,PROCESS").
    """
    if not spec:
        spec = DEFAULT_COLS

    if spec.upper() == "ALL":
        return [(name, acc) for name, _, acc in ALL_COLUMNS]

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


def format_session_table(
    sessions: list[SessionInfo],
    cols: str | None = None,
    *,
    all_metadata: bool = False,
) -> str:
    """Format sessions as an aligned table with configurable columns."""
    if not sessions:
        return "No tmux sessions found."

    columns = _resolve_columns(cols, all_metadata=all_metadata)
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


def format_fzf(
    sessions: list[SessionInfo],
    cols: str | None = None,
    *,
    all_metadata: bool = False,
) -> str:
    """Format sessions as tab-separated lines for fzf piping.

    First field is the raw session name (for selection), remaining
    fields are the human-readable column values.
    """
    if not sessions:
        return ""

    columns = _resolve_columns(cols, all_metadata=all_metadata)
    accessors = [acc for _, acc in columns]
    lines = []
    for s in sessions:
        fields = [s.name] + [acc(s) for acc in accessors]
        lines.append("\t".join(fields))
    return "\n".join(lines)


def format_status(info: dict, *, now: datetime | None = None) -> str:
    """Format detailed session status."""
    lines = [
        f"Session:  {info['name']}",
        f"Process:  {info['process']}",
        f"PID:      {info['pid']}",
        f"Dir:      {info['working_dir']}",
    ]

    agent = info.get("agent", {})
    if agent:
        lines.append(f"Agent:    {agent.get('type', 'unknown')} ({agent.get('state', 'unknown')})")

    meta = info.get("metadata", {})
    meta_updated_at = info.get("metadata_updated_at", {})
    if meta:
        lines.append("")
        lines.append("Metadata:")
        for k, v in sorted(meta.items()):
            if not _show_metadata_row(k, v):
                continue
            suffix = _metadata_age_suffix(k, v, meta, meta_updated_at, now=now)
            lines.append(f"  @{k} = {v}{suffix}")

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


def _resolve_columns(spec: str | None, *, all_metadata: bool = False) -> list[tuple[str, ColumnAccessor]]:
    columns = parse_cols(spec)
    if not all_metadata:
        return columns

    seen = {name for name, _ in columns}
    for name in _ALL_METADATA_COLUMN_NAMES:
        if name in seen:
            continue
        columns.append(_COL_BY_NAME[name])
        seen.add(name)
    return columns


def _pr_summary(metadata: dict[str, str]) -> str:
    pr = metadata.get("pr", "")
    if not pr:
        return "-"

    state = metadata.get("pr_state", "")
    if state == "MERGED":
        return f"{pr} M"
    if state == "CLOSED":
        return f"{pr} X"

    codes: list[str] = []

    review = metadata.get("pr_review", "")
    if review == "APPROVED":
        codes.append("A")
    elif review == "CHANGES_REQUESTED":
        codes.append("CR")
    elif review == "REVIEW_REQUIRED":
        codes.append("RR")
    elif review == "PENDING":
        codes.append("P")

    merge_state = metadata.get("pr_merge_state", "")
    if merge_state == "DIRTY":
        codes.append("D")
    elif merge_state == "BLOCKED":
        codes.append("B")
    elif merge_state == "CLEAN":
        codes.append("C")

    if not codes:
        return pr
    return f"{pr} {' '.join(codes)}"


def _show_metadata_row(key: str, value: str) -> bool:
    if key == "pr_merge_state" and value == "UNKNOWN":
        return False
    return True


def _metadata_age_suffix(
    key: str,
    value: str,
    metadata: dict[str, str],
    metadata_updated_at: dict[str, str],
    *,
    now: datetime | None = None,
) -> str:
    if _parse_iso_timestamp(value) is not None:
        return ""

    updated_at = metadata_updated_at.get(key, "")
    if not updated_at and key in _PR_REFRESH_KEYS:
        updated_at = metadata.get("last_refresh", "")

    relative = _relative_time(updated_at, now=now)
    if not relative:
        return ""
    return f" (updated {relative})"


def _relative_time(value: str, *, now: datetime | None = None) -> str:
    timestamp = _parse_iso_timestamp(value)
    if timestamp is None:
        return ""

    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    seconds = max(0, int((now_utc - timestamp).total_seconds()))

    if seconds < 5:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"

    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"

    days = hours // 24
    return f"{days}d ago"


def _parse_iso_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
