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

## Agent-specific behavior

### `codex`

State comes from Codex lifecycle events in the transcript, then `tp` confirms prompt readiness from the pane before considering the session sendable.

### `claude-code`

State comes from the latest meaningful Claude transcript entry:

- user message => `running`
- assistant message with `tool_use` => `running`
- assistant message with plain text completion => `completed`

`tp` then confirms that the Claude prompt has returned in the pane before it marks the session ready.

### Generic agents

Generic sessions do not have file-backed state. `tp` uses pane heuristics only.
