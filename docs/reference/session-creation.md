# Session Creation Reference

This page documents how `tp new` chooses between plain mode and profile mode.

## Plain Mode

Plain mode creates a detached tmux session. It may also launch an agent command directly inside that session.

Triggers:

- no profile settings apply
- explicit `--directory`
- explicit `--agent` without `--profile`, `--issue`, `--repo`, or `--no-agent`

Behavior:

- creates a tmux session
- optionally sets `@desc`
- optionally launches the `--agent` command
- optionally sends `--prompt` after the agent starts

In plain mode, `--prompt` requires `--agent`.

## Profile Mode

Profile mode creates a git worktree-backed tmux session using `~/.config/tmux-pilot/profiles.toml`.

Triggers:

- `--profile`
- `--issue`
- `--repo`
- `--no-agent`
- an existing `[default]` profile when plain mode is not forced

Behavior:

- resolves repo, worktree base, agent, `agent_args`, and branch prefix from the selected profile
- creates a worktree from `origin/main`
- records repo and branch metadata
- optionally launches the resolved agent
- optionally sends `--prompt`

## `profiles.toml` Fields

Supported fields:

- `repo`: local repository path
- `agent`: agent command to launch
- `agent_args`: stable flags appended to `agent`
- `worktree_base`: parent directory for created worktrees
- `branch_prefix`: branch prefix such as `feat` or `fix`

## Option Semantics

- `--agent`: command to launch in the session, such as `claude`, `claude-code`, or `codex`
- `--prompt`: initial text to send after the agent launches
- `--directory`: plain mode working directory
- `--repo`: profile mode repo override
- `--no-agent`: profile mode only; create the worktree/session but skip launching the configured agent
