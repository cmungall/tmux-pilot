"""argparse CLI entry point for tmux-pilot."""

from __future__ import annotations

import argparse
import json
import os
import sys

from pathlib import Path

from . import agent_sessions, core, display, hooks


_NEW_DESCRIPTION = """Create a tmux session.

Plain mode creates a detached tmux session with an optional working directory and description.
It can also launch a one-off agent command directly in that session with --agent and optionally
send an initial prompt with --prompt. Use --here to root the session in your current folder and
copy repo, branch, and worktree metadata from that checkout.

Profile mode launches a built-in or configured profile in-place with --directory or bootstraps a
task worktree with --repo. It can derive branches, create worktrees, launch the selected agent
command, and send an initial prompt once the agent becomes ready.

Built-in profiles:
  codex  -> codex --profile yolo
  claude -> claude --permission-mode bypassPermissions
  pi     -> pi --offline --no-extensions --no-skills --no-prompt-templates --no-themes --session-dir {worktree}/.tmux-pilot/pi/sessions
"""


_NEW_EPILOG = """Plain mode examples:
  tp new scratch
  tp new scratch -c ~/repos/myapp
  tp new --here
  tp new parser-pass --agent "codex --profile yolo --no-alt-screen"
  tp new parser-pass --agent "codex --profile yolo --no-alt-screen" --prompt "summarize the parser"

In-place profile examples:
  tp new docs-pass --profile codex -c ~/repos/tmux-pilot
  tp new review-pass --profile claude -c ~/repos/myapp
  tp new pi-local --profile pi -c ~/repos/pi-mono

Repo/bootstrap examples:
  tp new oauth-fix --profile codex --repo ~/repos/myapp
  tp new issue-771 --profile claude --repo ~/repos/myapp --issue 771
  tp new pi-smoke --profile pi --repo badlogic/pi-mono
  tp new cleanup --profile codex --repo ~/repos/myapp --branch chore/cleanup
  tp new backport --profile codex --repo ~/repos/myapp --base-ref origin/release/1.2

Config-driven examples:
  tp new api-cleanup --profile myapp
  tp new triage-pass --profile myapp --no-agent

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
        print(display.format_fzf(sessions, cols=args.cols, all_metadata=args.all_metadata))
    else:
        print(display.format_session_table(sessions, cols=args.cols, all_metadata=args.all_metadata))


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


def cmd_prod(args: argparse.Namespace) -> None:
    try:
        planned = core.plan_prod_actions(
            names=args.names or None,
            repo=args.repo,
            refresh=False if args.no_refresh else None,
        )
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(planned, indent=2))
        return

    if not planned:
        print("No sessions matched.")
        return

    matched = 0
    for action in planned:
        if action.get("skipped"):
            print(f"{action['session']}  skipped ({action.get('reason', 'no-rule')})")
            continue

        matched += 1
        pr_display = f"#{action['pr']}" if action.get("pr") else "-"
        header = (
            f"{action['session']}  rule={action['rule']}  pr={pr_display}"
            f"  review={action.get('pr_review') or '-'}  merge={action.get('pr_merge_state') or '-'}"
        )
        print(header)
        print(f"  {action['prompt']}")

        if args.dry_run:
            continue

        wait = args.wait
        timeout = args.timeout if args.timeout is not None else 30.0
        try:
            core.send_text(
                str(action["session"]),
                str(action["prompt"]),
                wait=wait,
                timeout=timeout,
            )
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)

    if matched == 0:
        print("No prod rules matched.")
        return

    if args.dry_run:
        print(f"Planned {matched} prod message(s).")
    else:
        print(f"Sent {matched} prod message(s).")


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


_ANSI_RESET = "\033[0m"
_ANSI_KEY = "\033[36m"
_ANSI_STRING = "\033[32m"
_ANSI_NUMBER = "\033[33m"
_ANSI_BOOL = "\033[35m"
_ANSI_NULL = "\033[2m"


def _style(text: str, code: str, *, color: bool) -> str:
    if not color:
        return text
    return f"{code}{text}{_ANSI_RESET}"


def _json_scalar(value: object, *, color: bool) -> str:
    if isinstance(value, str):
        return _style(json.dumps(value, ensure_ascii=False), _ANSI_STRING, color=color)
    if isinstance(value, bool):
        return _style("true" if value else "false", _ANSI_BOOL, color=color)
    if value is None:
        return _style("null", _ANSI_NULL, color=color)
    return _style(json.dumps(value, ensure_ascii=False), _ANSI_NUMBER, color=color)


def _json_key(value: str, *, color: bool) -> str:
    return _style(json.dumps(value, ensure_ascii=False), _ANSI_KEY, color=color)


def _json_inline(value: object, *, color: bool) -> str:
    if isinstance(value, dict):
        items = [f"{_json_key(str(key), color=color)}: {_json_inline(child, color=color)}" for key, child in value.items()]
        return "{" + ", ".join(items) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_json_inline(item, color=color) for item in value) + "]"
    return _json_scalar(value, color=color)


def _json_dump(value: object, *, indent: int = 0, color: bool = False) -> list[str]:
    prefix = " " * indent

    if isinstance(value, dict):
        if not value:
            return [f"{prefix}{{}}"]
        lines = [f"{prefix}{{"]
        items = list(value.items())
        for index, (key, child) in enumerate(items):
            comma = "," if index < len(items) - 1 else ""
            nested = _json_dump(child, indent=indent + 2, color=color)
            if len(nested) == 1:
                lines.append(f"{' ' * (indent + 2)}{_json_key(str(key), color=color)}: {nested[0].lstrip()}{comma}")
            else:
                lines.append(f"{' ' * (indent + 2)}{_json_key(str(key), color=color)}: {nested[0].lstrip()}")
                lines.extend(nested[1:])
                lines[-1] += comma
        lines.append(f"{prefix}}}")
        return lines

    if isinstance(value, list):
        if not value:
            return [f"{prefix}[]"]
        lines = [f"{prefix}["]
        for index, item in enumerate(value):
            comma = "," if index < len(value) - 1 else ""
            nested = _json_dump(item, indent=indent + 2, color=color)
            if len(nested) == 1:
                lines.append(f"{' ' * (indent + 2)}{nested[0].lstrip()}{comma}")
            else:
                lines.extend(nested)
                lines[-1] += comma
        lines.append(f"{prefix}]")
        return lines

    return [f"{prefix}{_json_scalar(value, color=color)}"]


def _yaml_scalar(value: object, *, color: bool) -> str:
    if isinstance(value, str):
        return _style(json.dumps(value, ensure_ascii=False), _ANSI_STRING, color=color)
    if isinstance(value, bool):
        return _style("true" if value else "false", _ANSI_BOOL, color=color)
    if value is None:
        return _style("null", _ANSI_NULL, color=color)
    return _style(json.dumps(value, ensure_ascii=False), _ANSI_NUMBER, color=color)


def _yaml_dump(value: object, *, indent: int = 0, color: bool = False) -> list[str]:
    prefix = " " * indent

    if isinstance(value, dict):
        if not value:
            return [f"{prefix}{{}}"]
        lines: list[str] = []
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}{_style(str(key), _ANSI_KEY, color=color)}:")
                lines.extend(_yaml_dump(child, indent=indent + 2, color=color))
            else:
                lines.append(f"{prefix}{_style(str(key), _ANSI_KEY, color=color)}: {_yaml_scalar(child, color=color)}")
        return lines

    if isinstance(value, list):
        if not value:
            return [f"{prefix}[]"]
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                nested = _yaml_dump(item, indent=indent + 2, color=color)
                first = nested[0].lstrip()
                lines.append(f"{prefix}- {first}")
                lines.extend(f"{prefix}  {line.lstrip()}" for line in nested[1:])
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item, color=color)}")
        return lines

    return [f"{prefix}{_yaml_scalar(value, color=color)}"]


def _should_use_color(mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    return sys.stdout.isatty()


def _compact_text(text: object) -> str:
    if text is None:
        return ""
    if isinstance(text, str):
        return " ".join(text.split())
    return " ".join(str(text).split())


def _item_summary(item: object) -> str:
    if isinstance(item, str):
        return _compact_text(item)
    if not isinstance(item, dict):
        return _compact_text(item)

    item_type = item.get("type")
    if item_type == "text":
        return _compact_text(item.get("text", ""))
    if item_type == "tool_use":
        name = _compact_text(item.get("name", "tool"))
        tool_input = item.get("input")
        if isinstance(tool_input, dict):
            command = _compact_text(tool_input.get("command", ""))
            if command:
                return f"tool {name}: {command}"
        return f"tool {name}"
    if item_type == "toolCall":
        name = _compact_text(item.get("name", "tool"))
        arguments = item.get("arguments")
        if isinstance(arguments, dict):
            command = _compact_text(arguments.get("command", ""))
            if command:
                return f"tool {name}: {command}"
        return f"tool {name}"
    return _compact_text(json.dumps(item, ensure_ascii=False, sort_keys=True))


def _content_summary(content: object) -> str:
    if isinstance(content, list):
        parts = [_item_summary(item) for item in content]
        return " | ".join(part for part in parts if part)
    if isinstance(content, dict):
        return _compact_text(json.dumps(content, ensure_ascii=False, sort_keys=True))
    return _compact_text(content)


def _payload_summary(payload: object) -> str:
    if isinstance(payload, dict):
        if "content" in payload:
            summary = _content_summary(payload.get("content"))
            if summary:
                return summary
        if "cwd" in payload:
            cwd = _compact_text(payload.get("cwd", ""))
            if cwd:
                return f"cwd={cwd}"
        return _compact_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return _compact_text(payload)


def _normalize_trace_record(agent_type: str, record: dict) -> dict[str, str]:
    timestamp = _compact_text(record.get("timestamp", ""))
    turn_id = _compact_text(record.get("turn_id") or record.get("uuid") or record.get("id") or "")
    kind = _compact_text(record.get("type", "")) or "record"
    role = ""
    summary = ""

    if agent_type == "codex":
        if kind in {"session_meta", "turn_context"}:
            role = "session" if kind == "session_meta" else "context"
            summary = _payload_summary(record.get("payload", {}))
        elif kind == "event_msg":
            role = "event"
            payload = record.get("payload", {})
            if isinstance(payload, dict):
                event_type = _compact_text(payload.get("type", "event"))
                turn_id = _compact_text(payload.get("turn_id", "")) or turn_id
                reason = _compact_text(payload.get("reason", ""))
                summary = event_type
                if reason:
                    summary = f"{summary} ({reason})"
            else:
                summary = _payload_summary(payload)
        else:
            summary = _payload_summary(record.get("payload", record))
    elif agent_type == "claude-code":
        message = record.get("message", {})
        if isinstance(message, dict):
            role = _compact_text(message.get("role", kind))
            summary = _content_summary(message.get("content"))
        if not summary:
            summary = _payload_summary(record)
    elif agent_type == "pi":
        if kind == "session":
            role = "session"
            cwd = _compact_text(record.get("cwd", ""))
            summary = f"cwd={cwd}" if cwd else _payload_summary(record)
        elif kind == "message":
            message = record.get("message", {})
            if isinstance(message, dict):
                role = _compact_text(message.get("role", "message"))
                summary = _content_summary(message.get("content"))
                stop_reason = _compact_text(message.get("stopReason", ""))
                if stop_reason and stop_reason not in {"stop"}:
                    summary = f"{summary} ({stop_reason})" if summary else stop_reason
            if not summary:
                summary = _payload_summary(record)
        else:
            summary = _payload_summary(record)
    else:
        if kind == "event_msg":
            role = "event"
            payload = record.get("payload", {})
            if isinstance(payload, dict):
                summary = _compact_text(payload.get("type", "event"))
                turn_id = _compact_text(payload.get("turn_id", "")) or turn_id
            else:
                summary = _payload_summary(payload)
        else:
            message = record.get("message")
            if isinstance(message, dict):
                role = _compact_text(message.get("role", kind))
                summary = _content_summary(message.get("content"))
            if not summary:
                summary = _payload_summary(record.get("payload", record))

    return {
        "timestamp": timestamp,
        "kind": kind or "-",
        "role": role or "-",
        "turn_id": turn_id or "-",
        "summary": summary or "-",
    }


def _trace_rows(trace: dict[str, object], *, lines: int, all_records: bool) -> list[dict[str, str]]:
    path = str(trace.get("path", "") or "")
    if not path:
        return []

    transcript_path = Path(path)
    record_limit = None if all_records else (lines if lines > 0 else 20)
    records = agent_sessions.read_transcript_records(transcript_path, limit=record_limit)
    agent_type = _compact_text(trace.get("agent", "")) or agent_sessions.infer_transcript_agent_type(transcript_path)
    return [_normalize_trace_record(agent_type, record) for record in records]


def _trace_tsv(rows: list[dict[str, str]]) -> str:
    header = ["timestamp", "kind", "role", "turn_id", "summary"]
    out = ["\t".join(header)]
    for row in rows:
        out.append("\t".join(row[field].replace("\t", " ") for field in header))
    return "\n".join(out)


def _role_style(label: str, *, color: bool) -> str:
    palette = {
        "user": _ANSI_STRING,
        "assistant": _ANSI_KEY,
        "event": _ANSI_NUMBER,
        "session": _ANSI_BOOL,
        "context": _ANSI_NULL,
        "toolresult": _ANSI_NUMBER,
        "bashexecution": _ANSI_NUMBER,
    }
    code = palette.get(label.lower(), _ANSI_KEY)
    return _style(label, code, color=color)


def _trace_formatted(rows: list[dict[str, str]], *, color: bool) -> str:
    if not rows:
        return ""
    width = max(len(row["role"]) for row in rows)
    lines = []
    for row in rows:
        label = row["role"]
        if label == "-" and row["kind"] != "-":
            label = row["kind"]
        turn = "" if row["turn_id"] in {"", "-"} else f" [{row['turn_id']}]"
        lines.append(
            f"{row['timestamp'] or '-'}  {_role_style(label.ljust(width), color=color)}{turn}  {row['summary']}"
        )
    return "\n".join(lines)


def _trace_content(
    trace: dict[str, object],
    *,
    show: str,
    lines: int,
    all_records: bool,
    color: bool,
) -> str:
    path = str(trace.get("path", "") or "")
    if not path:
        return ""

    transcript_path = Path(path)
    if show == "raw":
        if color:
            record_limit = None if all_records else (lines if lines > 0 else 20)
            records = agent_sessions.read_transcript_records(transcript_path, limit=record_limit)
            return "\n".join(_json_inline(record, color=True) for record in records)
        if all_records:
            try:
                return transcript_path.read_text(encoding="utf-8", errors="replace").rstrip()
            except OSError:
                return ""
        limit = lines if lines > 0 else 20
        return "\n".join(agent_sessions.read_transcript_tail(transcript_path, lines=limit))

    record_limit = None if all_records else (lines if lines > 0 else 20)
    records = agent_sessions.read_transcript_records(transcript_path, limit=record_limit)
    if show == "json":
        return "\n".join(_json_dump(records, color=color))
    if show == "yaml":
        return "\n".join(_yaml_dump(records, color=color))
    if show == "tsv":
        return _trace_tsv(_trace_rows(trace, lines=lines, all_records=all_records))
    if show == "formatted":
        return _trace_formatted(_trace_rows(trace, lines=lines, all_records=all_records), color=color)
    return ""


def cmd_trace(args: argparse.Namespace) -> None:
    try:
        trace = core.get_session_trace(
            args.name,
            refresh=args.refresh,
            lines=args.lines if args.show == "summary" else 0,
        )
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(trace, indent=2))
        return

    path = str(trace.get("path", "") or "")
    if not path:
        print(f"No transcript trace found for session '{args.name}'.")
        return

    if args.show != "summary":
        content = _trace_content(
            trace,
            show=args.show,
            lines=args.lines,
            all_records=args.all,
            color=_should_use_color(args.color),
        )
        if content:
            print(content)
        return

    lines = [
        f"Session:    {trace['session']}",
        f"Agent:      {trace.get('agent', '') or '-'}",
        f"Binding:    {trace.get('source', '') or '-'}",
        f"Pane Dir:   {trace.get('pane_working_dir', '') or '-'}",
        f"Trace Dir:  {trace.get('transcript_cwd', '') or '-'}",
        f"Path:       {path}",
    ]
    if trace.get("state"):
        lines.append(f"State:      {trace['state']}")
    if trace.get("timestamp"):
        lines.append(f"Last Event: {trace['timestamp']}")
    if trace.get("turn_id"):
        lines.append(f"Turn:       {trace['turn_id']}")

    tail = trace.get("tail", [])
    if isinstance(tail, list) and tail:
        lines.append("")
        lines.append("Tail:")
        lines.append("─" * 60)
        lines.extend(str(line) for line in tail)
        lines.append("─" * 60)

    print("\n".join(lines))


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


def cmd_refresh(args: argparse.Namespace) -> None:
    from . import reaper

    try:
        results = reaper.refresh_pr_metadata(names=args.names or None, repo=args.repo)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(results, indent=2))
        return

    if not results:
        print("No sessions to refresh.")
        return

    for result in results:
        if result.get("reason") == "no-branch":
            print(f"{result['session']}  skipped (no-branch)")
            continue

        pr = result.get("pr")
        pr_display = f"#{pr}" if pr is not None else "-"
        state = result.get("pr_state") or "-"
        review = result.get("pr_review") or "-"
        merge_state = result.get("pr_merge_state") or "-"
        print(
            f"{result['session']}  branch={result.get('branch', '-') or '-'}"
            f"  pr={pr_display}  state={state}  review={review}  merge={merge_state}"
        )


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
    p_ls.add_argument("--all-metadata", action="store_true", help="Append all known metadata columns")

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
    p_new.add_argument(
        "--profile",
        help="Built-in or configured profile name; built-ins include codex, claude, and pi",
    )
    p_new.add_argument("--issue", type=int, help="GitHub issue number used for branch naming and @desc")
    p_new.add_argument("--agent", help="One-off command override for plain mode or the selected profile")
    p_new.add_argument("--repo", help="Bootstrap from a local repo path, GitHub owner/repo, or GitHub URL")
    p_new.add_argument(
        "-c",
        "--directory",
        help="Existing directory for a plain session or an in-place profile launch",
    )
    p_new.add_argument("--branch", help="Override the derived task branch name, e.g. chore/name-cleanup")
    p_new.add_argument("--base-ref", help="Override the starting ref for a bootstrap worktree, e.g. origin/release/1.2")
    p_new.add_argument(
        "--no-agent",
        action="store_true",
        help="Create the session or worktree without launching the profile command",
    )
    p_new.add_argument("--prompt", help="Initial prompt to send after the agent becomes ready")
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

    # prod
    p_prod = sub.add_parser("prod", help="Send configured follow-up prompts based on session/PR state")
    p_prod.add_argument("names", nargs="*", help="Optional session names to prod")
    p_prod.add_argument("--repo", help="Filter by repo name (substring match)")
    p_prod.add_argument("--dry-run", action="store_true", help="Preview resolved prompts without sending")
    p_prod.add_argument("--json", action="store_true", help="Output resolved actions as JSON")
    p_prod.add_argument("--no-refresh", action="store_true", help="Use cached metadata instead of refreshing PR state first")
    p_prod.add_argument("--wait", action="store_true", help="Wait for agent readiness before every send")
    p_prod.add_argument("--timeout", type=float, help="Override send wait timeout for every matched rule")

    # jump
    p_jump = sub.add_parser("jump", help="Attach/switch to a session (fzf picker if no name)")
    p_jump.add_argument("name", nargs="?", default=None, help="Session name")

    # status
    p_status = sub.add_parser("status", help="Detailed session status")
    p_status.add_argument("name", help="Session name")

    # trace
    p_trace = sub.add_parser("trace", help="Inspect the transcript trace bound to a session")
    p_trace.add_argument("name", help="Session name")
    p_trace.add_argument("--refresh", action="store_true", help="Rescan by pane cwd before falling back to cached trace metadata")
    p_trace.add_argument("--json", action="store_true", help="Output trace info as JSON")
    p_trace.add_argument(
        "--show",
        choices=("summary", "raw", "json", "yaml", "tsv", "formatted"),
        default="summary",
        help="Show the trace summary or render transcript content as raw JSONL, pretty JSON, YAML, TSV, or a formatted timeline",
    )
    p_trace.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="Colorize human transcript output when using --show raw|json|yaml",
    )
    p_trace.add_argument("-n", "--lines", type=int, default=0, help="Show the last N transcript lines or records")
    p_trace.add_argument("--all", action="store_true", help="Show the full transcript instead of the last N lines or records")

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

    # refresh
    p_refresh = sub.add_parser("refresh", help="Refresh cached PR metadata")
    p_refresh.add_argument("names", nargs="*", help="Optional session names to refresh")
    p_refresh.add_argument("--repo", help="Filter by repo name (substring match)")
    p_refresh.add_argument("--json", action="store_true", help="Output refreshed state as JSON")

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
        "prod": cmd_prod,
        "jump": cmd_jump,
        "status": cmd_status,
        "trace": cmd_trace,
        "clean": cmd_clean,
        "kill": cmd_kill,
        "set": cmd_set,
        "get": cmd_get,
        "install-hooks": cmd_install_hooks,
        "reap": cmd_reap,
        "refresh": cmd_refresh,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()
