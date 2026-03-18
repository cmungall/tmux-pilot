"""argparse CLI entry point for tmux-pilot."""

from __future__ import annotations

import argparse
import json
import sys

from . import core, display


def cmd_ls(args: argparse.Namespace) -> None:
    sessions = core.list_sessions(
        status=args.status,
        repo=args.repo,
        process=args.process,
    )
    if args.json:
        print(json.dumps([s.to_dict() for s in sessions], indent=2))
    else:
        print(display.format_session_table(sessions))


def cmd_new(args: argparse.Namespace) -> None:
    if core.session_exists(args.name):
        print(f"Session '{args.name}' already exists.", file=sys.stderr)
        sys.exit(1)
    core.new_session(args.name, directory=args.directory, desc=args.desc)
    print(f"Created session '{args.name}'")


def cmd_peek(args: argparse.Namespace) -> None:
    if not core.session_exists(args.name):
        print(f"Session '{args.name}' not found.", file=sys.stderr)
        sys.exit(1)
    output = core.peek_session(args.name, lines=args.lines)
    print(output)


def cmd_send(args: argparse.Namespace) -> None:
    if not core.session_exists(args.name):
        print(f"Session '{args.name}' not found.", file=sys.stderr)
        sys.exit(1)
    core.send_keys(args.name, args.text)


def cmd_jump(args: argparse.Namespace) -> None:
    try:
        core.jump_session(args.name)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def cmd_status(args: argparse.Namespace) -> None:
    try:
        info = core.get_session_status(args.name)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    print(display.format_status(info))


def cmd_kill(args: argparse.Namespace) -> None:
    if not core.session_exists(args.name):
        print(f"Session '{args.name}' not found.", file=sys.stderr)
        sys.exit(1)
    core.kill_session(args.name)
    print(f"Killed session '{args.name}'")


def cmd_clean(args: argparse.Namespace) -> None:
    # Always preview first
    try:
        preview = core.clean_sessions(
            target=args.name,
            status_filter=args.status,
            dry_run=True,
        )
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    if not preview:
        print("No sessions to clean.")
        return

    if args.dry_run:
        print("Dry run — would clean:")
        for a in preview:
            extra = " (+ worktree)" if a.get("would_remove_worktree") else ""
            print(f"  {a['session']}{extra}")
        return

    if not args.force and not args.name:
        names = ", ".join(a["session"] for a in preview)
        resp = input(f"Clean {len(preview)} session(s): {names}? [y/N] ")
        if resp.lower() not in ("y", "yes"):
            print("Aborted.")
            return

    actions = core.clean_sessions(target=args.name, status_filter=args.status)
    for a in actions:
        parts = [f"killed {a['session']}"]
        if a.get("worktree_removed"):
            parts.append("removed worktree")
        if a.get("branch_deleted"):
            parts.append("deleted branch")
        print("  ".join(parts))
    print(f"Cleaned {len(actions)} session(s).")


def cmd_set(args: argparse.Namespace) -> None:
    if not core.session_exists(args.name):
        print(f"Session '{args.name}' not found.", file=sys.stderr)
        sys.exit(1)
    core.set_metadata(args.name, args.key, args.value)


def cmd_get(args: argparse.Namespace) -> None:
    if not core.session_exists(args.name):
        print(f"Session '{args.name}' not found.", file=sys.stderr)
        sys.exit(1)
    val = core.get_metadata(args.name, args.key)
    if val:
        print(val)
    else:
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tp",
        description="tmux-pilot: manage tmux sessions for AI coding agents",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )
    sub = parser.add_subparsers(dest="command")

    # ls
    p_ls = sub.add_parser("ls", help="List sessions with metadata")
    p_ls.add_argument("--json", action="store_true", help="Output as JSON")
    p_ls.add_argument("--status", help="Filter by status (e.g. active, done)")
    p_ls.add_argument("--repo", help="Filter by repo name (substring match)")
    p_ls.add_argument("--process", help="Filter by process (e.g. claude-code, python)")

    # new
    p_new = sub.add_parser("new", help="Create a new session")
    p_new.add_argument("name", help="Session name")
    p_new.add_argument("-c", "--directory", help="Working directory")
    p_new.add_argument("-d", "--desc", help="Description")

    # peek
    p_peek = sub.add_parser("peek", help="Show last N lines of scrollback")
    p_peek.add_argument("name", help="Session name")
    p_peek.add_argument("-n", "--lines", type=int, default=50, help="Lines to capture (default: 50)")

    # send
    p_send = sub.add_parser("send", help="Send text + Enter to a session")
    p_send.add_argument("name", help="Session name")
    p_send.add_argument("text", help="Text to send")

    # jump
    p_jump = sub.add_parser("jump", help="Attach/switch to a session (fzf picker if no name)")
    p_jump.add_argument("name", nargs="?", default=None, help="Session name")

    # status
    p_status = sub.add_parser("status", help="Detailed session status")
    p_status.add_argument("name", help="Session name")

    # clean
    p_clean = sub.add_parser("clean", help="Bulk cleanup of done-ish sessions + worktrees")
    p_clean.add_argument("name", nargs="?", default=None, help="Clean a specific session")
    p_clean.add_argument("--status", help="Filter by status (default: done/complete/finished/merged)")
    p_clean.add_argument("--dry-run", action="store_true", help="Preview without executing")
    p_clean.add_argument("--force", action="store_true", help="Skip confirmation prompt")

    # kill
    p_kill = sub.add_parser("kill", help="Kill a session")
    p_kill.add_argument("name", help="Session name")

    # set
    p_set = sub.add_parser("set", help="Set @metadata on a session")
    p_set.add_argument("name", help="Session name")
    p_set.add_argument("key", help="Metadata key")
    p_set.add_argument("value", help="Metadata value")

    # get
    p_get = sub.add_parser("get", help="Get @metadata from a session")
    p_get.add_argument("name", help="Session name")
    p_get.add_argument("key", help="Metadata key")

    return parser


def _get_version() -> str:
    from . import __version__
    return __version__


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    handlers = {
        "ls": cmd_ls,
        "new": cmd_new,
        "peek": cmd_peek,
        "send": cmd_send,
        "jump": cmd_jump,
        "status": cmd_status,
        "clean": cmd_clean,
        "kill": cmd_kill,
        "set": cmd_set,
        "get": cmd_get,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()
