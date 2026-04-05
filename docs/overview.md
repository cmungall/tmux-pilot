# Documentation

This project keeps the docs split by Diataxis:

- [Home](./index.md): the CLI-first landing page for the published docs site.
- [Tutorials](./tutorials/drive-a-kept-alive-agent-session.md): guided, end-to-end learning.
- [How-to guides](./how-to/create-sessions.md): choose between bare sessions, in-place profile launches, and worktree-backed task sessions.
- [How-to guides](./how-to/wait-for-interactive-agents.md): solve a specific operational task.
- [How-to guides](./how-to/start-task-sessions-with-profiles-and-worktrees.md): copy-paste examples for Codex, Claude Code, Pi, and task/worktree bootstrap from `tp new`.
- [Explanation](./explanation/file-backed-agent-state.md): why the agent-state model works the way it does.
- [Reference](./reference/agent-state.md): commands, states, transcript sources, and current behavior.
- [Reference](./reference/session-creation.md): exact `tp new` mode-selection and option semantics.

If you are new to `tp`, start with the tutorial. If you already use `tp` and need reliable follow-up sends to a busy agent, go straight to the how-to guide.

Local docs preview:

```bash
uv sync --group docs
uv run --group docs mkdocs serve
```
