# tmux-pilot

A thin, opinionated CLI for managing tmux sessions that run AI coding agents (Claude Code, Codex, etc).

**Why?** When you run multiple AI coding agents in parallel — each in its own tmux session — you need a way to list them, peek at their output, send follow-up instructions, and track metadata like status and branch. `tmux-pilot` wraps the fiddly tmux commands into a single `tp` command designed for both humans and AI orchestrators.

## Install

```bash
# pip
pip install tmux-pilot

# pipx (isolated install)
pipx install tmux-pilot

# uv
uv tool install tmux-pilot
```

**Requirements:** Python 3.10+, tmux. Optional: fzf (for `tp jump` picker).

Optional extras:

- `pip install "tmux-pilot[pathograph]"` installs `tp-pathograph-cx2`, a dismech pathograph -> CX2 converter for NDEx/IndexBio workflows.

## Quick Start

```bash
# Spin up a session for a feature branch
tp new auth-flow -c ~/repos/myapp -d "Implement OAuth2 login"

# Launch Claude Code inside it
tp send auth-flow "claude-code"

# Check on all your sessions
tp ls

# Peek at output without attaching
tp peek auth-flow -n 30

# Send a follow-up instruction
tp send auth-flow "now add tests for the auth module"

# Get detailed status
tp status auth-flow

# Done — tear it down
tp kill auth-flow
```

## Docs

Detailed documentation lives under [`docs/`](./docs/README.md) and is organized using Diataxis:

- tutorial: [`docs/tutorials/drive-a-kept-alive-agent-session.md`](./docs/tutorials/drive-a-kept-alive-agent-session.md)
- how-to: [`docs/how-to/wait-for-interactive-agents.md`](./docs/how-to/wait-for-interactive-agents.md)
- optional how-to: [`docs/how-to/convert-pathographs-to-cx2.md`](./docs/how-to/convert-pathographs-to-cx2.md)
- explanation: [`docs/explanation/file-backed-agent-state.md`](./docs/explanation/file-backed-agent-state.md)
- reference: [`docs/reference/agent-state.md`](./docs/reference/agent-state.md)

## Commands

### `tp ls` — List sessions

```bash
tp ls                          # table view
tp ls --json                   # JSON output (for AI orchestrators)
tp ls --status active          # filter by @status metadata
tp ls --repo myapp             # filter by repo (substring match)
tp ls --process claude-code    # filter by detected process
tp ls --json --status active   # combine filters with JSON
```

### `tp new` — Create a session

```bash
tp new NAME                    # bare session
tp new NAME -c ~/repos/myapp   # set working directory + @repo
tp new NAME -d "description"   # set @desc metadata
tp new NAME -c DIR -d DESC     # both
```

### `tp peek` — View scrollback without attaching

```bash
tp peek NAME                   # last 50 lines (default)
tp peek NAME -n 100            # last 100 lines
```

### `tp send` — Inject text into a session

```bash
tp send NAME "any command"     # sends text + Enter
tp send --wait NAME "follow-up instruction"
tp send NAME "claude-code --print 'fix the auth bug'"
```

### `tp jump` — Attach or switch to a session

```bash
tp jump NAME                   # attach (or switch if inside tmux)
tp jump                        # fzf picker (requires fzf)
```

### `tp status` — Detailed session info

Shows process, PID, working directory, all metadata, and the last 5 lines of scrollback.

```bash
tp status NAME
```

### `tp set` / `tp get` — Session metadata

Metadata is stored as tmux user options (`@`-prefixed). Built-in keys: `repo`, `task`, `desc`, `status`, `origin`, `branch`, `needs`.

```bash
tp set NAME status "waiting-for-review"
tp set NAME branch "feat/auth"
tp get NAME status
```

## For AI Orchestrators

`tmux-pilot` is designed to be called by AI coding agents and orchestration scripts, not just humans. The `--json` flag on `tp ls` outputs machine-readable JSON:

```bash
$ tp ls --json
[
  {
    "name": "auth-flow",
    "process": "claude-code",
    "working_dir": "/home/user/repos/myapp",
    "metadata": {
      "desc": "Implement OAuth2 login",
      "status": "active",
      "repo": "/home/user/repos/myapp"
    }
  }
]
```

A typical orchestrator loop:

```bash
# Poll for sessions needing attention
tp ls --json --status needs-review | jq '.[].name' | while read name; do
  tp peek "$name" -n 20
  # ... decide what to do ...
  tp send "$name" "next instruction"
  tp set "$name" status active
done
```

## Key Features

- **Core session manager stays lightweight** — the `tp` session commands remain stdlib-driven; pathograph CX2 conversion is an optional extra
- **Process detection** — distinguishes claude-code vs codex vs bare shell
- **Metadata** — tmux user options (@status, @desc, @repo, @branch, etc.)
- **Peek without attaching** — critical for orchestrators monitoring sessions
- **JSON output** — `tp ls --json` for machine-readable session data
- **Filtering** — `tp ls --status/--repo/--process` to narrow results
- **fzf integration** — optional fuzzy picker for `tp jump`

## License

MIT
