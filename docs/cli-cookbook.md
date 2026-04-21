# CLI Cookbook

Use this page as the copy-paste companion for everyday `tp` work. Every section is a concrete shell workflow.

## See What Is Running

```bash
tp ls
tp ls --status active
tp ls --process codex
tp ls --repo tmux-pilot
tp refresh --repo tmux-pilot
tp ls --json
tp ls --all-metadata
tp ls --cols NAME,STATUS,PROCESS,BRANCH
tp ls --cols NAME,PR,STATUS,DIR
```

Use `tp refresh` before dashboard-style `tp ls` views when you want current PR metadata. Use `--json` when another tool needs structured session data. Use `--cols` when you want a tighter table for terminal work.

The compact `PR` column combines the PR number with short codes:

- `M` merged
- `X` closed
- `A` approved
- `CR` changes requested
- `RR` review required
- `P` pending
- `D` dirty/conflicted
- `B` blocked
- `C` clean

## Start Sessions In Place

### Bare tmux sessions

```bash
tp new scratch
tp new scratch -c ~/repos/myapp
tp new scratch --here
tp new --here
```

### Launch built-in profiles in an existing checkout

```bash
tp new docs-pass --profile codex -c ~/repos/tmux-pilot
tp new review-pass --profile claude -c ~/repos/myapp
tp new pi-local --profile pi -c ~/repos/pi-mono
```

### Override the launched command explicitly

```bash
tp new parser-pass -c ~/repos/myapp --agent "codex --profile yolo --no-alt-screen"
tp new shell-pass -c ~/repos/myapp --agent zsh
```

## Bootstrap Task Worktrees

### From a local checkout

```bash
tp new auth-fix --profile codex --repo ~/repos/myapp
tp new cleanup --profile codex --repo ~/repos/myapp --branch chore/cleanup
tp new backport --profile codex --repo ~/repos/myapp --base-ref origin/release/1.2
```

### From GitHub

```bash
tp new pi-smoke --profile pi --repo badlogic/pi-mono
tp new cli-pass --profile codex --repo https://github.com/cmungall/tmux-pilot.git
```

### From an issue number

```bash
tp new issue-771 --profile claude --repo ~/repos/myapp --issue 771
```

That flow is useful when you want the issue title pulled into `@desc` and a deterministic task branch derived from the issue number.

## Attach, Peek, and Check Status

```bash
tp jump docs-pass
tp peek docs-pass -n 30
tp peek docs-pass -n 100
tp status docs-pass
tp trace docs-pass
```

Use `tp peek` when you need recent output but do not want to take over your terminal with `tmux attach`.

## Send Follow-Up Work Safely

### Fire-and-forget send

```bash
tp send docs-pass "summarize the auth module"
```

### Wait for readiness first

```bash
tp send --wait docs-pass "now add regression tests"
tp send --wait --timeout 120 docs-pass "continue with the next failing case"
```

### Common steering loop

```bash
tp peek docs-pass -n 50
tp send --wait docs-pass "address the failing tests before refactoring"
tp status docs-pass
```

## Work With Metadata

```bash
tp set docs-pass status needs-review
tp set docs-pass branch feat/auth-fix
tp get docs-pass status
tp get docs-pass branch
```

Built-in metadata is also surfaced through `tp status` and `tp ls --json`.

When you need the transcript binding rather than pane scrollback, use:

```bash
tp trace docs-pass
tp trace docs-pass --refresh
tp trace docs-pass --show raw --lines 10
tp trace docs-pass --show json
tp trace docs-pass --show yaml
tp trace docs-pass --show tsv
tp trace docs-pass --show formatted
tp trace docs-pass --show yaml --color always
```

## Refresh PR Metadata And Build A Review Dashboard

```bash
tp refresh
tp refresh --repo myapp
tp ls --cols NAME,PR,STATUS,DIR --repo myapp
tp ls --all-metadata --repo myapp
tp status docs-pass
```

Use this when `tp` is acting as the orchestration dashboard for many task worktrees. `tp status` shows the cached PR fields with relative freshness, and `tp ls --all-metadata` exposes the raw `PR_NUM`, `PR_STATE`, `REVIEW`, `MERGE_STATE`, and `LAST_REFRESH` columns when you need full detail.

## Clean Up Sessions And Worktrees

### Kill one session immediately

```bash
tp kill docs-pass
```

### Preview bulk cleanup

```bash
tp clean --dry-run
tp clean --status merged --dry-run
tp clean docs-pass --dry-run
```

### Apply cleanup

```bash
tp clean --force
tp clean docs-pass --force
```

`tp clean` is the local cleanup tool: remove done-ish sessions and their worktrees when you are ready.

## Reap Sessions Whose PRs Are Merged

```bash
tp reap --dry-run
tp reap --force
tp reap --include-no-pr --dry-run
```

`tp reap` is the PR-aware cleanup path: it checks whether the branch has landed upstream before removing the session/worktree.

## Install Git Hooks

```bash
tp install-hooks
tp install-hooks --path ~/.config/git/hooks
tp install-hooks --uninstall
```

Use this when you want git lifecycle hooks wired to `tp`'s session cleanup flows.

## A Good Daily Loop

```bash
# Start the task in a worktree
tp new oauth-fix --profile codex --repo ~/repos/myapp

# Refresh review and merge state across the repo
tp refresh --repo myapp

# See the compact dashboard
tp ls --cols NAME,PR,STATUS,DIR --repo myapp

# Check progress without attaching
tp peek oauth-fix -n 40

# Push the next instruction once the agent is ready
tp send --wait oauth-fix "write focused tests around the callback parser"

# Inspect full state and metadata
tp status oauth-fix

# Clean up after the branch lands
tp reap --dry-run
tp reap --force
```
