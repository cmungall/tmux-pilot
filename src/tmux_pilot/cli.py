"""argparse CLI entry point for tmux-pilot."""

from __future__ import annotations

import argparse
import json
import os
import sys

from pathlib import Path

from . import core, display, hooks


_NEW_DESCRIPTION = """Create a tmux session.

Plain mode creates a detached tmux session with an optional working directory and description.
It can also launch an agent command directly in that session with --agent and optionally send an
initial prompt with --prompt. Use --here to root the session in your current folder and copy repo,
branch, and worktree metadata from that checkout.

Profile mode launches a configured profile in-place with --directory or bootstraps a task worktree
with --repo. It can derive branches, create worktrees, launch the selected agent command, and send
an initial prompt once the agent becomes ready.
"""


_NEW_EPILOG = """Examples:
  tp new scratch -c ~/repos/myapp
  tp new -c ~/repos/myapp
  tp new --here
  tp new scratch --here --jump
  tp new foo-codex-test --agent codex --prompt "1+3"
  tp new review-771 --profile dismech --issue 771
  tp new codex-fix --profile default --agent codex --prompt "Write tests for the parser"
  tp new cleanup --profile codex --repo ~/repos/myapp --branch chore/cleanup

Agent values are shell commands, not fixed enums. Use the command you would launch inside tmux.
Common values: claude, claude-code, codex, pi
"""


def cmd_ls(args: argparse.Namespace) -> None:
    sessions = core.list_sessions(
        status=args.status,
        repo=args.repo,
        process=args.process,
    )
    if args.json:
        print(json.dumps([s.to_dict() for s in sessions], indent=2))
    elif args.fzf:
        print(display.format_fzf(sessions, cols=args.cols))
    else:
        print(display.format_session_table(sessions, cols=args.cols))


def cmd_new(args: argparse.Namespace) -> None:
    directory = args.directory
    used_here = False
    if args.here:
        if args.directory:
            print("--here cannot be combined with --directory", file=sys.stderr)
            sys.exit(1)
        directory = os.getcwd()
        used_here = True

    name = args.name
    inferred_name = False
    if not name:
        if directory:
            try:
                name = core.infer_session_name_for_directory(directory)
                inferred_name = True
            except RuntimeError as e:
                print(str(e), file=sys.stderr)
                sys.exit(1)
        else:
            print("Session name is required unless --directory or --here is provided.", file=sys.stderr)
            sys.exit(1)

    if core.session_exists(name):
        if inferred_name:
            name = core.uniqueify_session_name(name)
        else:
            print(f"Session '{name}' already exists.", file=sys.stderr)
            sys.exit(1)

    try:
        if core.should_use_profile_mode(
            profile_name=args.profile,
            issue=args.issue,
            agent=args.agent,
            repo=args.repo,
            branch=args.branch,
            base_ref=args.base_ref,
            no_agent=args.no_agent,
            prompt=args.prompt,
            directory=directory,
        ):
            if used_here:
                raise RuntimeError("--here is plain-mode only; use --directory or --repo")
            core.create_profile_session(
                name,
                profile_name=args.profile,
                issue=args.issue,
                agent=args.agent,
                repo=args.repo,
                directory=directory,
                branch=args.branch,
                base_ref=args.base_ref,
                no_agent=args.no_agent,
                prompt=args.prompt,
                desc=args.desc,
            )
        else:
            if args.prompt and not args.agent:
                raise RuntimeError("--prompt requires --agent in plain mode; use --profile to send a prompt via a profile agent")
            core.new_session(name, directory=directory, desc=args.desc)
            if used_here and directory:
                core.apply_directory_metadata(name, directory)
            if args.agent:
                core.launch_agent_session(
                    name,
                    args.agent,
                    prompt=args.prompt,
                    expected_cwd=directory,
                )
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    print(f"Created session '{name}'")
    if args.jump:
        try:
            core.jump_session(name)
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)


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
    try:
        core.send_text(
            args.name,
            args.text,
            wait=args.wait,
            timeout=args.timeout,
        )
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


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


def cmd_install_hooks(args: argparse.Namespace) -> None:
    hooks_dir = Path(args.path) if args.path else None
    if args.uninstall:
        actions = hooks.uninstall_hooks(hooks_dir)
        for h in actions["hooks_removed"]:
            print(f"  removed {h}")
        if actions["restored_hooks_path"]:
            print(f"  restored core.hooksPath -> {actions['restored_hooks_path']}")
        else:
            print("  unset core.hooksPath")
        print("Uninstalled tmux-pilot hooks.")
    else:
        actions = hooks.install_hooks(hooks_dir)
        for h in actions["hooks_installed"]:
            print(f"  installed {h}")
        print(f"Hooks in {actions['hooks_dir']}, core.hooksPath configured.")


def cmd_reap(args: argparse.Namespace) -> None:
    from . import reaper
    results = reaper.reap_sessions(
        dry_run=args.dry_run,
        force=args.force,
        include_no_pr=args.include_no_pr,
    )
    if not results:
        print("No sessions to reap.")
        return

    if args.dry_run:
        print("Dry run -- would reap:")
        for r in results:
            flag = r.get("reason", "")
            print(f"  {r['session']}  branch={r.get('branch', '?')}  pr=#{r.get('pr', '-')}  [{flag}]")
        return

    if not args.force:
        names = ", ".join(r["session"] for r in results if r.get("action") == "confirm")
        if names:
            resp = input(f"Reap session(s): {names}? [y/N] ")
            if resp.lower() not in ("y", "yes"):
                print("Aborted.")
                return
            # Actually reap after confirmation
            results = reaper.reap_sessions(
                dry_run=False,
                force=True,
                include_no_pr=args.include_no_pr,
            )

    for r in results:
        parts = [r["session"]]
        if r.get("killed"):
            parts.append("killed")
        if r.get("worktree_removed"):
            parts.append("worktree removed")
        if r.get("branch_deleted"):
            parts.append("branch deleted")
        if r.get("skipped"):
            parts.append(f"skipped ({r.get('reason', '')})")
        print("  ".join(parts))
    reaped = sum(1 for r in results if r.get("killed"))
    print(f"Reaped {reaped} session(s).")


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
    p_ls.add_argument("--cols", help="Columns to show: mnemonics (NSP) or names (NAME,STATUS,PROCESS)")
    p_ls.add_argument("--fzf", action="store_true", help="Tab-separated output for fzf piping")
    p_ls.add_argument("--status", help="Filter by status (e.g. active, done)")
    p_ls.add_argument("--repo", help="Filter by repo name (substring match)")
    p_ls.add_argument("--process", help="Filter by process (e.g. claude-code, python)")

    # new
    p_new = sub.add_parser(
        "new",
        help="Create a bare session or a profile-backed task session",
        description=_NEW_DESCRIPTION,
        epilog=_NEW_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_new.add_argument(
        "name",
        nargs="?",
        help="Session name; optional with --directory or --here, where it defaults to the directory or worktree name",
    )
    p_new.add_argument("--profile", help="Named profile from ~/.config/tmux-pilot/profiles.toml")
    p_new.add_argument("--issue", type=int, help="GitHub issue number to derive metadata from")
    p_new.add_argument("--agent", help="Override the profile's agent command or plain-mode launch command")
    p_new.add_argument("--repo", help="Bootstrap from a local repo path or GitHub owner/repo[/url]")
    p_new.add_argument("-c", "--directory", help="Working directory for a non-bootstrap session or in-place profile launch")
    p_new.add_argument("--branch", help="Override the derived task branch name")
    p_new.add_argument("--base-ref", help="Override the base ref used when creating a task worktree")
    p_new.add_argument("--no-agent", action="store_true", help="Create the session without launching an agent")
    p_new.add_argument("--prompt", help="Initial prompt to send to the agent after startup")
    p_new.add_argument("--here", action="store_true", help="Plain mode only: use the current directory and infer git metadata from it")
    p_new.add_argument("-d", "--desc", help="Description")
    p_new.add_argument("-j", "--jump", action="store_true", help="Attach or switch to the new session immediately after creating it")

    # peek
    p_peek = sub.add_parser("peek", help="Show last N lines of scrollback")
    p_peek.add_argument("name", help="Session name")
    p_peek.add_argument("-n", "--lines", type=int, default=50, help="Lines to capture (default: 50)")

    # send
    p_send = sub.add_parser("send", help="Send text + Enter to a session")
    p_send.add_argument("name", help="Session name")
    p_send.add_argument("text", help="Text to send")
    p_send.add_argument("--wait", action="store_true", help="Wait for the agent to become ready before sending")
    p_send.add_argument("--timeout", type=float, default=30.0, help="Seconds to wait with --wait (default: 30)")

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

    # install-hooks
    p_hooks = sub.add_parser("install-hooks", help="Install git hooks for session lifecycle")
    p_hooks.add_argument("--path", help="Custom hooks directory (default: ~/.config/git/hooks/)")
    p_hooks.add_argument("--uninstall", action="store_true", help="Remove hooks and restore previous hooksPath")

    # reap
    p_reap = sub.add_parser("reap", help="Reap sessions whose PRs are merged")
    p_reap.add_argument("--dry-run", action="store_true", help="Preview without executing")
    p_reap.add_argument("--force", action="store_true", help="Skip confirmation prompt")
    p_reap.add_argument("--include-no-pr", action="store_true", help="Also flag clean sessions with no PR")

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
        "install-hooks": cmd_install_hooks,
        "reap": cmd_reap,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()
