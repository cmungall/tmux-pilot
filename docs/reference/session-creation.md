# Session Creation Reference

This page documents how `tp new` chooses between plain mode and profile mode.

## Plain Mode

Plain mode creates a detached tmux session. It may also launch an agent command directly inside that session.

Triggers:

- no profile settings apply
- explicit `--here`
- explicit `--agent` without `--profile`, `--issue`, `--repo`, or `--no-agent`
- explicit `--directory` when profile/worktree bootstrap mode is not otherwise selected

Behavior:

- creates a tmux session
- optionally sets `@desc`
- optionally launches the `--agent` command
- optionally sends `--prompt` after the agent starts
- verifies the pane cwd when plain mode was given `--directory` or `--here`
- when `--here` is used, records inferred repo/branch/worktree metadata from the current checkout
- when `NAME` is omitted with `--directory` or `--here`, infers the session name from the repo/worktree root
- when an inferred name collides, auto-uniqueifies it with `-1`, `-2`, and so on

In plain mode, `--prompt` requires `--agent`.

## Profile Mode

Profile mode creates a git worktree-backed tmux session using `~/.config/tmux-pilot/profiles.toml`.

Triggers:

- `--profile`
- `--issue`
- `--repo`
- `--no-agent`
- `--branch`
- `--base-ref`
- an existing `[default]` profile when plain mode is not forced

Behavior:

- resolves repo, worktree base, agent, `agent_args`, and branch prefix from the selected profile
- uses `--directory` for an in-place launch when provided
- otherwise creates a task worktree from the configured repo and base ref
- records repo and branch metadata
- optionally launches the resolved agent
- optionally sends `--prompt`
- verifies that the pane cwd stays on the requested directory or created worktree when launching the agent

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
- `NAME`: optional when `--directory` or `--here` is present
- `--directory`: existing working directory; plain mode creates a bare session there, while profile mode launches the selected profile in place
- `--here`: plain mode shortcut for “use the current working directory and infer git metadata”
- `--repo`: profile mode bootstrap source or repo override
- `--no-agent`: profile mode only; create the worktree/session but skip launching the configured agent
- `--jump`: attach or switch to the new session immediately after creation

## Known Limitations

- Brand-new Codex repos and worktrees may stop at a trust prompt before the normal input prompt appears. This is expected behavior, not a mysterious readiness failure.
- `tp` does not yet expose first-class `trust-prompt`, `shell-idle`, or `exited` readiness states.
- `tp new` does not yet provide a built-in `--setup-cmd` or a first-class `--worktree-from ... --branch ...` workflow.
- Those missing setup/worktree orchestration features should be treated as product gaps or blockers, not as places to normalize bespoke shell-script workarounds.
