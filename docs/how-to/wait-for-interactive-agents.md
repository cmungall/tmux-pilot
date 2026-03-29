# Wait For Interactive Agents

Use this guide when you already have a live Codex or Claude Code session and need to send another instruction without racing the prompt.

## Send a follow-up instruction

```bash
tp send --wait SESSION_NAME "your next instruction"
```

Example:

```bash
tp send --wait auth-flow "add regression tests for the login callback"
```

## Set a timeout

The default wait timeout is 30 seconds. Override it when the task in the session is expected to run longer:

```bash
tp send --wait --timeout 120 auth-flow "continue with the next step"
```

## Check why a wait is taking time

Use status and scrollback from another terminal:

```bash
tp status auth-flow
tp peek auth-flow -n 60
```

## What `--wait` actually waits for

For supported agents, `tp` combines:

- transcript-backed lifecycle state
- prompt readiness from the tmux pane

That means `tp` does not send as soon as the task is merely complete. It waits until the agent is both done and back at a prompt that can accept input.

## Supported agents

- `codex`
- `claude-code`

Other agents still fall back to pane heuristics only.

## If the session is generic shell output

You can still send without waiting:

```bash
tp send SESSION_NAME "echo hello"
```

Or use `--wait` anyway and let `tp` fall back to prompt detection from pane output.
