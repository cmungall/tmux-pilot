# File-Backed Agent State

`tp` needs two answers before it can safely send a follow-up instruction into a live agent session:

1. Is the agent still working on the current task?
2. Has the interactive prompt actually returned?

Pane scraping alone is not enough to answer both reliably. Terminal output is presentation, not state. Prompts can remain visible in scrollback while the agent is still running, and a terminal can show task completion text before the input box is ready again.

## The model

For supported agents, `tp` uses two sources of truth:

- transcript files on disk for lifecycle state
- tmux pane output for prompt readiness

The transcript tells `tp` whether the agent is running or has finished a turn. The pane tells `tp` whether the interactive UI has actually returned to a sendable prompt.

`tp send --wait` only proceeds when both conditions line up.

## Why transcripts

Structured transcript files are more stable than terminal text. They survive scrollback truncation and expose agent events directly instead of forcing `tp` to infer state from visible strings.

Current supported sources:

- Codex transcripts under `$CODEX_HOME/sessions` or `~/.codex/sessions`
- Claude Code transcripts under `CLAUDE_PROJECTS_DIR` or `~/.claude/projects`

## Why keep tmux pane checks

Transcript state alone is still not enough. An agent can mark a task complete before its input prompt is usable again. `tp` therefore keeps a second readiness check against the live pane.

This is the key merge:

- transcript says whether the task is `running`, `completed`, or interrupted
- pane says whether the prompt is visibly back and ready for input

## Fallback behavior

For agents without a file-backed plugin, `tp` falls back to pane heuristics only. That keeps `tp` broadly usable while allowing higher-confidence behavior for supported interactive agents.
