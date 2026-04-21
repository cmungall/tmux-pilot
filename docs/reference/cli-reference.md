# CLI Reference

This page is the compact command reference for `tp`. For longer walkthroughs, use the [CLI Cookbook](../cli-cookbook.md).

## Command Index

| Command | Purpose |
| --- | --- |
| `tp ls` | list sessions and filter them by status, repo, or process |
| `tp new` | create a bare session or a profile-backed task session |
| `tp peek` | view recent scrollback without attaching |
| `tp send` | send the next instruction into a live session |
| `tp jump` | attach or switch to a session |
| `tp status` | inspect process, cwd, metadata, and recent output |
| `tp trace` | inspect the transcript trace bound to a session |
| `tp clean` | remove done-ish sessions and their worktrees |
| `tp kill` | kill a session immediately |
| `tp set` / `tp get` | manage tmux-backed session metadata |
| `tp install-hooks` | install or remove git lifecycle hooks |
| `tp refresh` | refresh cached PR metadata without cleanup |
| `tp reap` | remove sessions whose PRs are merged |

## `tp ls`

```bash
tp ls
tp ls --status active
tp ls --process claude-code
tp ls --repo myapp
tp ls --all-metadata
tp ls --cols NAME,STATUS,PROCESS,BRANCH
tp ls --cols NAME,PR,STATUS,DIR
tp ls --json
```

`PR` is a compact summary column. It starts with the PR number and appends short codes when available:

- `M` merged
- `X` closed
- `A` approved
- `CR` changes requested
- `RR` review required
- `P` pending
- `D` dirty/conflicted
- `B` blocked
- `C` clean

## `tp new`

Built-in profiles:

- `codex` -> `codex --profile yolo`
- `claude` -> `claude --permission-mode bypassPermissions`
- `pi` -> `pi --offline --no-extensions --no-skills --no-prompt-templates --no-themes --session-dir {worktree}/.tmux-pilot/pi/sessions`

### Plain sessions

```bash
tp new scratch
tp new scratch -c ~/repos/myapp
tp new scratch --here
tp new --here
```

### Explicit profile launches

```bash
# Starts `codex --profile yolo` in ~/repos/tmux-pilot
tp new docs-pass --profile codex -c ~/repos/tmux-pilot

# Starts `claude --permission-mode bypassPermissions` in ~/repos/myapp
tp new review-pass --profile claude -c ~/repos/myapp

# Starts `pi --offline --no-extensions --no-skills --no-prompt-templates --no-themes --session-dir ~/repos/pi-mono/.tmux-pilot/pi/sessions`
tp new pi-local --profile pi -c ~/repos/pi-mono
```

### Repo/bootstrap flow

```bash
# Creates branch feat/oauth-fix and worktree ~/worktrees/myapp-oauth-fix
tp new oauth-fix --profile codex --repo ~/repos/myapp

# Creates branch fix/771-issue-771 and pulls the issue title into @desc
tp new issue-771 --profile claude --repo ~/repos/myapp --issue 771

# Clones ~/repos/pi-mono first if needed, then creates ~/worktrees/pi-mono-pi-smoke
tp new pi-smoke --profile pi --repo badlogic/pi-mono
```

### Useful overrides

```bash
tp new review-771 --profile claude --repo ~/repos/myapp --branch fix/review-771
tp new backport --profile codex --repo ~/repos/myapp --base-ref origin/release/1.2
tp new parser-pass --profile codex -c ~/repos/myapp --prompt "summarize the parser module"
tp new triage-pass --profile codex --repo ~/repos/myapp --no-agent
```

## `tp peek`

```bash
tp peek docs-pass
tp peek docs-pass -n 100
```

## `tp send`

```bash
tp send docs-pass "summarize the failing tests"
tp send --wait docs-pass "write regression coverage for the callback"
tp send --wait --timeout 90 docs-pass "continue with the next failure"
```

## `tp jump`

```bash
tp jump docs-pass
tp jump
```

Running `tp jump` without a name opens the `fzf` picker when `fzf` is installed.

## `tp status`

```bash
tp status docs-pass
```

`tp status` shows:

- detected process
- working directory
- tmux metadata
- metadata freshness for cached fields such as PR state
- cached trace metadata when a transcript has been resolved
- current agent state
- recent scrollback

## `tp trace`

```bash
tp trace docs-pass
tp trace docs-pass --refresh
tp trace docs-pass --json
tp trace docs-pass --show raw --lines 10
tp trace docs-pass --show json
tp trace docs-pass --show yaml
tp trace docs-pass --show tsv
tp trace docs-pass --show formatted
tp trace docs-pass --show yaml --color always
```

`tp trace` resolves the transcript associated with a session, preferring cached `@trace_agent` / `@trace_path` metadata and falling back to a cwd-based scan when needed. This is the command to use when you want to verify which chat/session trace a tmux session is actually bound to.

- `--json` prints the trace binding metadata as JSON
- `--show raw` prints raw JSONL lines from the transcript
- `--show json` pretty-prints transcript records as a JSON array
- `--show yaml` renders transcript records in a YAML-like view
- `--show tsv` emits normalized transcript rows with tab-separated columns
- `--show formatted` renders a readable timestamped transcript timeline
- `--color auto|always|never` controls ANSI color for `--show raw|json|yaml|formatted`

## `tp clean`

```bash
tp clean --dry-run
tp clean --status merged --dry-run
tp clean docs-pass --force
tp clean --force
```

## `tp kill`

```bash
tp kill docs-pass
```

## `tp set` and `tp get`

```bash
tp set docs-pass status needs-review
tp set docs-pass branch feat/oauth-fix
tp get docs-pass status
```

## `tp install-hooks`

```bash
tp install-hooks
tp install-hooks --path ~/.config/git/hooks
tp install-hooks --uninstall
```

## `tp refresh`

```bash
tp refresh
tp refresh docs-pass
tp refresh --repo myapp
tp refresh --json
```

`tp refresh` updates cached PR metadata only. It writes `@pr`, `@pr_state`, `@pr_review`, `@pr_merge_state`, and `@last_refresh`, but it does not kill sessions, remove worktrees, or delete branches.

## Trace Metadata

When `tp` resolves a transcript for a session, it caches:

- `@trace_agent`
- `@trace_path`

These cached fields are visible in `tp status`, `tp ls --all-metadata`, and `tp ls --json`.

## `tp reap`

```bash
tp reap --dry-run
tp reap --force
tp reap --include-no-pr --dry-run
```

`tp reap --dry-run` still refreshes and persists safe PR metadata before deciding what would be reaped.

## Notes On Current Behavior

- Codex trust prompts in brand-new repos/worktrees are expected and are not yet surfaced as a dedicated first-class state.
- `tp send --wait` currently helps once the session is back at a sendable prompt.
- The most reliable explicit Codex launch command today is still `codex --profile yolo --no-alt-screen` for long-lived sessions you plan to steer repeatedly.
