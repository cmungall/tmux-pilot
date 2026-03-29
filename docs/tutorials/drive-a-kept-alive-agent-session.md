# Drive A Kept-Alive Agent Session

This tutorial walks through a single long-lived tmux session that stays alive while you send follow-up work into it.

## Goal

By the end, you will:

- create a tmux session with `tp`
- launch an interactive agent inside it
- send work into the live session
- wait for the agent to become ready before sending more work
- inspect status without attaching

## 1. Create a session

```bash
tp new demo-agent -c ~/repos/myapp -d "Interactive agent rollout"
```

This creates a detached tmux session named `demo-agent` rooted at your project directory.

## 2. Launch an interactive agent

Claude Code:

```bash
tp send demo-agent "claude"
```

Codex:

```bash
tp send demo-agent "codex --profile yolo --no-alt-screen"
```

Attach if you want to confirm the prompt once:

```bash
tp jump demo-agent
```

Detach from tmux when the agent is back at its normal prompt.

## 3. Send the first task

```bash
tp send demo-agent "write a short summary of the auth module"
```

This types the text into the live session and submits it.

## 4. Send follow-up work safely

Interactive agents are not always ready for a second instruction immediately after the first one. Use `--wait` when the session may still be working:

```bash
tp send --wait demo-agent "now add tests for the auth module"
```

`tp` waits for the agent to return to a sendable state before it types the next instruction.

## 5. Check status without attaching

```bash
tp status demo-agent
tp peek demo-agent -n 40
```

`tp status` shows the detected agent and its state. `tp peek` shows recent scrollback without taking over the terminal.

## 6. Clean up

```bash
tp kill demo-agent
```

## What to do next

- For a task-focused guide, see [Wait For Interactive Agents](../how-to/wait-for-interactive-agents.md).
- For the design rationale, see [File-Backed Agent State](../explanation/file-backed-agent-state.md).
