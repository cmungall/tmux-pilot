# Agent State Reference

This page documents the current agent-state and readiness behavior used by `tp status`, `tp ls --json`, and `tp send --wait`.

## `tp send --wait`

```bash
tp send --wait NAME "instruction"
tp send --wait --timeout 90 NAME "instruction"
```

Behavior:

- polls the active session until the agent is ready
- sends the text only after readiness is confirmed
- raises an error if the timeout is reached first

Every successful `tp send` also records a sortable UTC timestamp in the session metadata as `last_send`.

## State values

Current built-in states:

- `idle`: prompt is ready for more input
- `running`: agent is still processing the current task
- `completed`: latest turn finished
- `interrupted`: latest turn was interrupted
- `error`: latest turn failed
- `unknown`: no reliable signal was found

Readiness is slightly stricter than state:

- `idle` is ready
- `completed` is ready only after the prompt is visibly back
- `running` is not ready

States that are not first-class yet:

- trust prompt
- shell idle
- exited

## Metadata

`tp` stores session metadata as tmux user options.

Relevant keys for steering:

- `last_send`: updated after a successful `tp send`

## Transcript sources

### Codex

- transcript root: `$CODEX_HOME/sessions`
- default root when unset: `~/.codex/sessions`
- session matching: tmux pane working directory to transcript `cwd`

### Claude Code

- transcript root: `CLAUDE_PROJECTS_DIR`
- default root when unset: `~/.claude/projects`
- session matching: tmux pane working directory to transcript `cwd`

`CLAUDE_PROJECTS_DIR` is primarily useful for tests or nonstandard layouts. Claude Code itself normally writes under `~/.claude/projects`.

### Pi

- default transcript root: `~/.pi/agent/sessions/--<cwd>--`
- configurable root: `PI_CODING_AGENT_DIR/sessions/--<cwd>--`
- built-in `tp` profile root: `{worktree}/.tmux-pilot/pi/sessions`
- session matching: tmux pane working directory to session header `cwd`

## Agent-specific behavior

### `codex`

State comes from Codex lifecycle events in the transcript, then `tp` confirms prompt readiness from the pane before considering the session sendable.

### `claude-code`

State comes from the latest meaningful Claude transcript entry:

- user message => `running`
- assistant message with `tool_use` => `running`
- assistant message with plain text completion => `completed`

`tp` then confirms that the Claude prompt has returned in the pane before it marks the session ready.

### `pi`

Pi uses a mix of pane heuristics and session-file state:

- assistant `stopReason=toolUse` => `running`
- user, tool result, or bash execution entries => `running`
- assistant `stopReason=stop` => `completed`
- assistant `stopReason=aborted` => `interrupted`
- assistant `stopReason=error` => `error`

If no session file is available yet, `tp` falls back to the visible Pi footer and command palette prompt markers in the pane.

### Generic agents

Generic sessions do not have file-backed state. `tp` uses pane heuristics only.

## Known gaps

- Codex trust prompts in brand-new repos and worktrees are expected, but `tp` does not yet surface a dedicated `trust-prompt` state.
- `tp send --wait` starts helping once the interactive agent has reached a sendable prompt. It does not auto-accept trust bootstrap.
