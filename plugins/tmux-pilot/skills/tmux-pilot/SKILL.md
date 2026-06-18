---
name: tmux-pilot
description: Use the tmux-pilot `tp` CLI to orchestrate tmux sessions for AI coding agents. Use when the user wants to start, inspect, attach to, send instructions to, resume, refresh PR metadata for, or clean up Codex, Claude Code, Pi, or generic tmux-backed task sessions and git worktrees.
---

# Tmux Pilot

## Overview

Use `tp` as the front door for managing long-running AI coding-agent sessions in tmux. Prefer `tp` over raw `tmux` when the task involves session metadata, git worktrees, PR state, agent readiness, or cleanup.

## Preflight

Run these checks before depending on `tp`:

```bash
tp --version
tmux -V
tp ls --json
```

If `tp` is missing, suggest installing it with one of:

```bash
uv tool install tmux-pilot
pipx install tmux-pilot
pip install tmux-pilot
```

When operating inside a repository, check the local worktree first:

```bash
git status -sb
```

Do not run destructive cleanup commands without a preview unless the user explicitly requested forceful cleanup.

## Start Sessions

Choose the startup pattern that matches the user's intent.

Existing checkout:

```bash
tp new docs-pass --profile codex -c ~/repos/myapp
tp new review-pass --profile claude -c ~/repos/myapp
tp new pi-local --profile pi -c ~/repos/pi-mono
```

Task branch and worktree bootstrap:

```bash
tp new oauth-fix --profile codex --repo ~/repos/myapp
tp new issue-771 --profile claude --repo ~/repos/myapp --issue 771
tp new pi-smoke --profile pi --repo badlogic/pi-mono
```

Useful overrides:

```bash
tp new cleanup --profile codex --repo ~/repos/myapp --branch chore/cleanup
tp new backport --profile codex --repo ~/repos/myapp --base-ref origin/release/1.2
tp new triage-pass --profile codex --repo ~/repos/myapp --no-agent
tp new parser-pass -c ~/repos/myapp --agent "codex --profile yolo --no-alt-screen"
tp new shell-pass -c ~/repos/myapp --agent zsh
```

Use `--prompt` only when the initial instruction is ready to send after the agent starts:

```bash
tp new docs-pass --profile codex -c ~/repos/myapp --prompt "summarize the docs layout"
```

## Inspect And Steer

Use non-invasive inspection before attaching:

```bash
tp ls
tp ls --cols NAME,PR,STATUS,DIR
tp peek docs-pass -n 80
tp status docs-pass
tp trace docs-pass
```

Send follow-up work with readiness checks when possible:

```bash
tp send --wait docs-pass "continue with the next failing test"
tp send --wait --timeout 120 docs-pass "address the review comments and push fixes"
```

Use `tp jump docs-pass` only when the user wants an interactive attach/switch.

## PR Metadata And Production Prompts

Refresh PR metadata before making a dashboard or sending PR-driven follow-ups:

```bash
tp refresh --repo myapp
tp ls --cols NAME,PR,STATUS,DIR --repo myapp
tp ls --all-metadata --repo myapp
```

Use `tp prod --dry-run` before sending configured follow-up prompts:

```bash
tp prod --dry-run --repo myapp
tp prod --repo myapp --wait
```

`tp refresh` writes cached metadata but does not kill sessions, remove worktrees, or delete branches.

## Resume Worktrees

When tmux sessions are gone but worktrees remain:

```bash
tp wt status
tp wt ls --repo myapp
tp wt refresh --repo myapp
tp wt resume oauth-fix --dry-run
tp wt resume oauth-fix --profile codex
tp wt resume oauth-fix -c
```

Use `-c/--continue` when the detected agent supports resuming the previous conversation.

## Cleanup

Always preview first:

```bash
tp clean --dry-run
tp reap --dry-run
tp wt clean
```

Apply cleanup only after confirmation or explicit user instruction:

```bash
tp clean --force
tp reap --force
tp wt clean --force
```

Use `tp reap` for PR-aware cleanup after branches land. Use `tp reap --include-dead` only when intentionally cleaning branchless sessions whose worktree has disappeared; it kills the tmux session only.

## Output Expectations

Report:

- session names created, inspected, resumed, or removed
- worktree paths and branches when `--repo` bootstrapping is used
- prompts sent to agents
- whether commands were dry-run previews or destructive actions
- any blockers, such as missing `tp`, missing `tmux`, dirty worktrees, trust prompts, or agent readiness timeouts
