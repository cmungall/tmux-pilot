# Session Creation Reference

This page documents how `tp new` chooses between plain mode and profile mode.

Built-in profile shortcuts:

- `codex` -> `codex --profile yolo`
- `claude` -> `claude --permission-mode bypassPermissions`
- `pi` -> `pi --offline --no-extensions --no-skills --no-prompt-templates --no-themes --session-dir {worktree}/.tmux-pilot/pi/sessions`

## Plain Mode

Plain mode creates a detached tmux session. It may also launch an agent command directly inside that session.

Triggers:

- no profile settings apply
- explicit `--here`
- explicit `--agent` without `--profile`, `--issue`, `--repo`, or `--no-agent`
- explicit `--directory` when no resolved profile applies

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

Examples:

```bash
tp new scratch
tp new scratch -c ~/repos/myapp
tp new --here
tp new parser-pass --agent "codex --profile yolo --no-alt-screen" --prompt "summarize the parser"
```

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

- resolves repo, worktree base, clone base, command, env, base ref, prompt timeout, and branch prefix from the selected profile
- uses `--directory` for an in-place launch unless bootstrap semantics were explicitly requested with `--repo`, `--issue`, `--branch`, or `--base-ref`
- otherwise creates a task worktree from the configured repo and base ref
- records repo and branch metadata
- optionally launches the resolved agent
- optionally sends `--prompt`
- verifies that the pane cwd stays on the requested directory or created worktree when launching the agent

Bootstrap worktrees are named `<repo>-<session>` by default. If `NAME` already starts with `<repo>-`, that session name is reused as the worktree leaf directory instead of repeating the repo prefix.

Examples:

```bash
# In-place launch in an existing checkout
tp new docs-pass --profile codex -c ~/repos/tmux-pilot

# Config-driven bootstrap using repo/base_ref from profiles.toml
tp new api-cleanup --profile myapp

# Explicit repo bootstrap from GitHub
tp new pi-smoke --profile pi --repo badlogic/pi-mono
```

## `profiles.toml` Fields

Supported fields:

- `extends`: inherit settings from another profile
- `repo`: local repository path
- `worktree_base`: parent directory for created worktrees
- `clone_base`: parent directory used when bootstrapping from a repo clone
- `base_ref`: default base ref used when creating a worktree branch
- `branch_prefix`: branch prefix such as `feat` or `fix`
- `command`: agent command to launch
- `env`: environment variables to set for the launched agent command
- `prompt_wait_timeout`: how long to wait before sending the initial prompt
- `agent`: legacy alias for `command`; still accepted
- `agent_args`: legacy stable flags appended to `agent`; still accepted

## Option Semantics

- `--agent`: command to launch in the session, such as `claude`, `claude-code`, or `codex`
- `--prompt`: initial text to send after the agent launches
- `NAME`: optional when `--directory` or `--here` is present
- `--directory`: existing working directory; plain mode creates a bare session there, while a resolved profile launches in place unless `--repo`, `--issue`, `--branch`, or `--base-ref` asks for bootstrap
- `--here`: plain mode shortcut for “use the current working directory and infer git metadata”
- `--repo`: profile mode bootstrap source or repo override
- `--no-agent`: profile mode only; create the worktree/session but skip launching the configured agent
- `--jump`: attach or switch to the new session immediately after creation

## Known Limitations

- Brand-new Codex repos and worktrees may stop at a trust prompt before the normal input prompt appears. This is expected behavior, not a mysterious readiness failure.
- `tp` does not yet expose first-class `trust-prompt`, `shell-idle`, or `exited` readiness states.
- `tp new` does not yet provide a built-in `--setup-cmd` or a first-class `--worktree-from ... --branch ...` workflow.
- Those missing setup/worktree orchestration features should be treated as product gaps or blockers, not as places to normalize bespoke shell-script workarounds.
