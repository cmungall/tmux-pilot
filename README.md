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

## Quick Start

```bash
# Start Codex in an existing checkout.
# tmux-pilot runs: codex --profile yolo
tp new auth-flow --profile codex -c ~/repos/myapp

# Start Claude Code in an existing checkout.
# tmux-pilot runs: claude --permission-mode bypassPermissions
tp new review-pass --profile claude -c ~/repos/myapp

# Start Pi in an existing checkout.
# tmux-pilot runs: pi --session-dir ~/repos/pi-mono/.tmux-pilot/pi/sessions
tp new pi-local --profile pi -c ~/repos/pi-mono

# Bootstrap a task branch + worktree from a local repo, then launch Codex there.
# Default branch: feat/oauth-fix
# Default worktree: ~/worktrees/myapp-oauth-fix
tp new oauth-fix --profile codex --repo ~/repos/myapp -d "Fix OAuth callback handling"

# Bootstrap from GitHub if the repo is not cloned locally yet.
# The repo is cloned to ~/repos/pi-mono first, then a worktree is created.
tp new pi-smoke --profile pi --repo badlogic/pi-mono

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
- how-to: [`docs/how-to/create-sessions.md`](./docs/how-to/create-sessions.md)
- how-to: [`docs/how-to/wait-for-interactive-agents.md`](./docs/how-to/wait-for-interactive-agents.md)
- how-to: [`docs/how-to/start-task-sessions-with-profiles-and-worktrees.md`](./docs/how-to/start-task-sessions-with-profiles-and-worktrees.md)
- explanation: [`docs/explanation/file-backed-agent-state.md`](./docs/explanation/file-backed-agent-state.md)
- reference: [`docs/reference/agent-state.md`](./docs/reference/agent-state.md)
- reference: [`docs/reference/session-creation.md`](./docs/reference/session-creation.md)

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
tp new -c ~/repos/myapp        # infer session name from the directory
tp new NAME --here             # use cwd and infer repo/branch/worktree metadata
tp new --here                  # infer the session name from cwd/worktree
tp new NAME --here -j          # create, then auto-jump into the session
tp new NAME -d "description"   # set @desc metadata
tp new NAME -c DIR -d DESC     # both

# Launch a built-in agent profile in-place
tp new NAME --profile codex -c ~/repos/myapp

# Bootstrap a task branch + worktree from a repo, then launch the profile
tp new NAME --profile claude --repo ~/repos/myapp

# `--repo` accepts a local path, GitHub owner/repo, or GitHub URL
tp new NAME --profile pi --repo badlogic/pi-mono
tp new NAME --profile pi --repo https://github.com/badlogic/pi-mono.git

# Override branch/base selection when needed
tp new NAME --profile codex --repo ~/repos/myapp --branch chore/name-cleanup
tp new NAME --profile codex --repo ~/repos/myapp --base-ref origin/release/1.2
```

Concrete profile examples:

```bash
# Launches `codex --profile yolo` in ~/repos/myapp
tp new auth-pass --profile codex -c ~/repos/myapp

# Launches `claude --permission-mode bypassPermissions` in ~/repos/myapp
tp new review-pass --profile claude -c ~/repos/myapp

# Launches `pi --session-dir ~/repos/pi-mono/.tmux-pilot/pi/sessions`
tp new pi-local --profile pi -c ~/repos/pi-mono
```

When `--repo` is used, `tp new` now handles the full task bootstrap flow:

- resolves or clones the repo
- derives a task branch from the session name (or `--issue`)
- creates a git worktree under the configured worktree base
- starts the requested agent inside that worktree

Concrete bootstrap examples:

```bash
# Creates branch `feat/oauth-fix`, worktree `~/worktrees/myapp-oauth-fix`,
# then launches `codex --profile yolo` inside that worktree.
tp new oauth-fix --profile codex --repo ~/repos/myapp

# Creates branch `fix/771-issue-771`, fetches the issue title for @desc,
# then launches `claude --permission-mode bypassPermissions`.
tp new issue-771 --profile claude --repo ~/repos/myapp --issue 771

# If ~/repos/pi-mono does not exist yet, clone it first.
# Then create branch `feat/pi-smoke`, worktree `~/worktrees/pi-mono-pi-smoke`,
# and launch Pi with a worktree-local session dir.
tp new pi-smoke --profile pi --repo badlogic/pi-mono

# Pin the branch name or starting point when needed.
tp new cleanup --profile codex --repo ~/repos/myapp --branch chore/cleanup
tp new backport --profile codex --repo ~/repos/myapp --base-ref origin/release/1.2
```

Built-in launch profiles:

- `codex`: `codex --profile yolo`
- `claude`: `claude --permission-mode bypassPermissions`
- `pi`: `pi --session-dir {worktree}/.tmux-pilot/pi/sessions`

Recommended profile config lives at `~/.config/tmux-pilot/profiles.toml`:

```toml
[default]
extends = "codex"
worktree_base = "~/worktrees"
clone_base = "~/repos"

[profiles.pi]
extends = "pi"
branch_prefix = "task"

[profiles.myapp]
extends = "codex"
repo = "~/repos/myapp"
branch_prefix = "feat"
base_ref = "origin/main"
```

`extends` can target another configured profile or one of the built-in profiles above. Config values override the inherited profile, so you can keep reusable agent defaults separate from repo-specific task defaults.

For interactive Codex sessions, `codex --profile yolo --no-alt-screen` plus `tp send --wait` is the current best-supported flow. Brand-new repos and worktrees can still stop at a Codex trust prompt before normal readiness begins. `tp` now verifies the tmux pane cwd before and immediately after agent launch and fails loudly if the shell or agent drifts out of the requested directory.

`--here` is plain-mode only. It uses your current working directory as the session directory, records inferred git metadata such as repo root, current branch, and whether the checkout is a linked worktree, and can infer the session name from that directory when you omit `NAME`. If that inferred name already exists, `tp new` auto-suffixes it as `-1`, `-2`, and so on. `-j/--jump` attaches or switches to the new session immediately after creation.

Concrete config-driven examples:

```bash
# Uses `[default]`, so this launches `codex --profile yolo`
# even though no `--profile` flag was passed.
tp new rename-types -c ~/repos/myapp

# Uses the repo/base branch from `[profiles.myapp]`,
# so `--repo ~/repos/myapp` is not needed here.
tp new api-cleanup --profile myapp

# Uses the customized Pi profile, so the derived branch is `task/pi-smoke`
# instead of the default `feat/pi-smoke`.
tp new pi-smoke --profile pi --repo badlogic/pi-mono
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

- **Zero dependencies** — stdlib only (subprocess calls to tmux)
- **Process detection** — distinguishes claude-code vs codex vs bare shell
- **Metadata** — tmux user options (@status, @desc, @repo, @branch, etc.)
- **Peek without attaching** — critical for orchestrators monitoring sessions
- **JSON output** — `tp ls --json` for machine-readable session data
- **Filtering** — `tp ls --status/--repo/--process` to narrow results
- **fzf integration** — optional fuzzy picker for `tp jump`

## License

MIT
