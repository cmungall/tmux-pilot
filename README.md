# tmux-pilot

A thin, opinionated CLI for managing tmux sessions that run AI coding agents (Claude Code, Codex, etc). Both humans and AI orchestrators use it.

## Install

```bash
pip install tmux-pilot
```

Or with uv:

```bash
uv pip install tmux-pilot
```

## Usage

```bash
tp ls                          # list sessions with metadata
tp new NAME [-c DIR] [-d DESC] # create session with metadata
tp peek NAME [-n LINES]        # show last N lines of scrollback
tp send NAME "message"         # inject text + Enter into a session
tp jump [NAME]                 # attach/switch to session (fzf picker if no name)
tp status NAME                 # detailed status: metadata, process, scrollback
tp kill NAME                   # kill session
tp set NAME key value          # set @metadata
tp get NAME key                # get @metadata
```

## Examples

### Create a session for Claude Code

```bash
tp new my-feature -c ~/repos/my-project -d "Implement auth flow"
tp send my-feature "claude-code --print 'implement oauth2 login'"
```

### Monitor from an AI orchestrator

```bash
# Check what's running
tp ls

# Peek at output without attaching
tp peek my-feature -n 100

# Send follow-up instructions
tp send my-feature "now add tests for the auth module"
```

### Metadata

```bash
tp set my-feature status "waiting-for-review"
tp set my-feature branch "feat/auth"
tp get my-feature status
```

## Key Features

- **Zero dependencies** — stdlib only (subprocess calls to tmux)
- **Process detection** — distinguishes claude-code vs codex vs bare shell
- **Metadata** — tmux user options (@status, @desc, @repo, @branch, etc.)
- **Peek without attaching** — critical for AI orchestrators that monitor sessions
- **fzf integration** — optional fuzzy picker for `tp jump`

## Requirements

- Python 3.10+
- tmux
- Optional: fzf (for `tp jump` picker)

## License

MIT
