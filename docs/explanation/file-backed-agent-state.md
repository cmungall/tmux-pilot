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

To keep one tmux session associated with one agent/chat trace, `tp` now also caches the resolved transcript binding on the session itself. Once a transcript has been resolved, later checks can reuse that binding instead of re-discovering it purely from cwd every time.

## Why transcripts

Structured transcript files are more stable than terminal text. They survive scrollback truncation and expose agent events directly instead of forcing `tp` to infer state from visible strings.

Current supported sources:

- Codex transcripts under `$CODEX_HOME/sessions` or `~/.codex/sessions`
- Claude Code transcripts under `CLAUDE_PROJECTS_DIR` or `~/.claude/projects`
- Pi session files under `PI_CODING_AGENT_DIR/sessions` or the built-in worktree-local `.tmux-pilot/pi/sessions`

The initial discovery path is still cwd-based, but it now feeds a cached session binding (`@trace_agent`, `@trace_path`) that can be inspected with `tp trace`.

## Why keep tmux pane checks

Transcript state alone is still not enough. An agent can mark a task complete before its input prompt is usable again. `tp` therefore keeps a second readiness check against the live pane.

This is the key merge:

- transcript says whether the task is `running`, `completed`, or interrupted
- pane says whether the prompt is visibly back and ready for input

## Fallback behavior

For agents without a file-backed plugin, `tp` falls back to pane heuristics only. That keeps `tp` broadly usable while allowing higher-confidence behavior for supported interactive agents.

## Operational conclusions

Real-world use has clarified a few product boundaries:

- `tp new --agent "codex --profile yolo --no-alt-screen"` plus `tp send --wait` is a meaningful improvement over the older one-shot send model.
- Codex trust prompts are normal in brand-new repos and worktrees. They should be treated as an explicit product state, not hand-waved away as a transient glitch.
- Session metadata alone is not enough to trust launch correctness. `tp` must verify the live pane cwd before and immediately after agent launch, because a shell or agent can drift away from the requested directory while metadata still looks correct.
- Once a transcript has been discovered, the session should keep using that trace as its stable binding. This gives orchestrators a durable handle for future features such as conversation summaries and richer state inspection.
- Low-level setup commands and first-class worktree-aware creation are still missing features. When users need them, that should be recorded as a blocker or roadmap item rather than normalized as a permanent shell-script workaround.
