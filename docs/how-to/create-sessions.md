# Create Sessions

Use this guide when you want to understand which `tp new` flags create a plain tmux session and which ones create a profile-backed worktree session.

## Create a plain tmux session

```bash
tp new scratch
tp new scratch -c ~/repos/myapp
```

This creates a detached tmux session only. No git worktree is created.

## Create a plain tmux session and launch an agent

```bash
tp new foo-codex-test --agent codex
tp new foo-codex-test --agent codex --prompt "1+3"
```

Here, `--agent` is the command to launch inside the new tmux session.

Common values:

- `claude`
- `claude-code`
- `codex`

## Create a profile-backed worktree session

```bash
tp new review-771 --profile dismech --issue 771
tp new auth-fix --profile default
```

Profile mode creates a worktree from the configured repository, records repo and branch metadata, and can launch the configured agent automatically.

## Override the profile's agent

```bash
tp new review-771 --profile default --agent codex --prompt "Write tests first"
```

Use `--profile` when you want worktree/profile behavior and also want to override the profile's default agent command.

## `--directory` vs `--repo`

- `--directory`: plain mode working directory
- `--repo`: profile mode repository override

Do not use `--directory` with profile mode.

## Where agent flags belong

Use `--agent` for the executable name or command. Put stable flags in `profiles.toml` as `agent_args`.

Example:

```toml
[default]
repo = "~/repos/myapp"
agent = "codex"
agent_args = "--profile yolo --no-alt-screen"
```
