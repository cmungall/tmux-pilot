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
| `tp clean` | remove done-ish sessions and their worktrees |
| `tp kill` | kill a session immediately |
| `tp set` / `tp get` | manage tmux-backed session metadata |
| `tp install-hooks` | install or remove git lifecycle hooks |
| `tp reap` | remove sessions whose PRs are merged |

## `tp ls`

```bash
tp ls
tp ls --status active
tp ls --process claude-code
tp ls --repo myapp
tp ls --cols NAME,STATUS,PROCESS,BRANCH
tp ls --json
```

## `tp new`

Built-in profiles:

- `codex` -> `codex --profile yolo`
- `claude` -> `claude --permission-mode bypassPermissions`
- `pi` -> `pi --session-dir {worktree}/.tmux-pilot/pi/sessions`

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

# Starts `pi --session-dir ~/repos/pi-mono/.tmux-pilot/pi/sessions`
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
- current agent state
- recent scrollback

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

## `tp reap`

```bash
tp reap --dry-run
tp reap --force
tp reap --include-no-pr --dry-run
```

## Notes On Current Behavior

- Codex trust prompts in brand-new repos/worktrees are expected and are not yet surfaced as a dedicated first-class state.
- `tp send --wait` currently helps once the session is back at a sendable prompt.
- The most reliable explicit Codex launch command today is still `codex --profile yolo --no-alt-screen` for long-lived sessions you plan to steer repeatedly.
