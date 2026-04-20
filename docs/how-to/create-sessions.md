# Create Sessions

Use this guide when you want to understand which `tp new` flags create a plain tmux session, which ones launch a profile in place, and which ones create a profile-backed worktree session.

Built-in profiles:

- `codex` -> `codex --profile yolo`
- `claude` -> `claude --permission-mode bypassPermissions`
- `pi` -> `pi --offline --no-extensions --no-skills --no-prompt-templates --no-themes --session-dir {worktree}/.tmux-pilot/pi/sessions`

## Create a plain tmux session

```bash
tp new scratch
tp new scratch -c ~/repos/myapp
tp new scratch --here
tp new --here
tp new -c ~/repos/myapp
```

This creates a detached tmux session only. No git worktree is created.

`--here` is plain-mode sugar for “use the directory I am currently in”, and it also records inferred git metadata from that checkout.

When you omit `NAME` in plain mode and provide `--here` or `--directory`, `tp` infers the session name from the repo or worktree root. That means a linked worktree such as `~/worktrees/dismech-prev-1` defaults to a session name like `dismech-prev-1`.

If that inferred name already exists, `tp` auto-uniqueifies it as `dismech-prev-1-1`, `dismech-prev-1-2`, and so on. Explicitly provided names still fail on collision.

## Create a plain tmux session and launch an agent

```bash
tp new foo-codex-test --agent codex
tp new foo-codex-test --agent codex --prompt "1+3"
tp new foo-codex-test -c ~/worktrees/myrepo --agent "codex --profile yolo --no-alt-screen"
```

Here, `--agent` is the command to launch inside the new tmux session.

Common values:

- `claude`
- `claude-code`
- `codex`

For kept-alive Codex sessions, `codex --profile yolo --no-alt-screen` plus `tp send --wait` is the most reliable current flow.

Brand-new repos and worktrees can still stop at a Codex trust prompt before the normal input prompt appears. That trust prompt is expected. `tp send --wait` helps after startup, but trust bootstrap is not yet a first-class workflow.

When you create a session with `-c DIR`, `tp` now verifies that the tmux pane is actually in `DIR` before it launches the agent and immediately after launch. If the shell or the agent drifts to another directory, `tp` fails loudly instead of silently launching in the wrong tree.

## Jump into the session immediately

```bash
tp new scratch --here --jump
tp new review-771 --profile dismech --issue 771 --jump
```

`-j`/`--jump` attaches or switches to the new session as soon as it has been created.

## Launch a profile in an existing checkout

```bash
tp new docs-pass --profile codex -c ~/repos/tmux-pilot
tp new review-pass --profile claude -c ~/repos/myapp
tp new pi-local --profile pi -c ~/repos/pi-mono
```

For built-in profiles and custom profiles without a configured `repo`, this uses the selected profile's command in the existing checkout passed by `--directory`. No new worktree is created.

Those commands launch:

- `codex --profile yolo`
- `claude --permission-mode bypassPermissions`
- `pi --offline --no-extensions --no-skills --no-prompt-templates --no-themes --session-dir ~/repos/pi-mono/.tmux-pilot/pi/sessions`

## Create a profile-backed worktree session

```bash
tp new review-771 --profile dismech --issue 771
tp new auth-fix --profile default
tp new pi-smoke --profile pi --repo badlogic/pi-mono
```

Profile mode creates a worktree from the configured repository, records repo and branch metadata, and can launch the configured agent automatically.

Concrete outcomes:

- `tp new auth-fix --profile codex --repo ~/repos/myapp` derives branch `feat/auth-fix`, creates `~/worktrees/myapp-auth-fix`, and launches `codex --profile yolo`.
- `tp new issue-771 --profile claude --repo ~/repos/myapp --issue 771` derives branch `fix/771-issue-771`, copies the issue title into `@desc`, and launches `claude --permission-mode bypassPermissions`.
- `tp new pi-smoke --profile pi --repo badlogic/pi-mono` clones `~/repos/pi-mono` first if needed, creates `~/worktrees/pi-mono-pi-smoke`, and launches `pi --offline --no-extensions --no-skills --no-prompt-templates --no-themes --session-dir ~/worktrees/pi-mono-pi-smoke/.tmux-pilot/pi/sessions`.

## Override the profile's agent

```bash
tp new review-771 --profile default --agent codex --prompt "Write tests first"
```

Use `--profile` when you want worktree/profile behavior and also want to override the profile's default agent command.

## `--directory` vs `--repo` vs `--here`

- `--directory`: use an existing checkout as the working directory. In plain mode this creates a bare session there. With an explicit built-in or repo-less profile, it launches the selected profile in place.
- `--repo`: profile mode bootstrap source. `tp` resolves or clones the repo, creates a task worktree, and launches the selected profile there.
- `--here`: plain mode only. It uses the current directory, infers repo/branch/worktree metadata, and can infer the session name when `NAME` is omitted.

## Where agent flags belong

Use `--agent` for one-off command overrides. Put stable launch settings in `profiles.toml` as `command`.

Example:

```toml
[default]
repo = "~/repos/myapp"
command = ["codex", "--profile", "yolo", "--no-alt-screen"]
```
