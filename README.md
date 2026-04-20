# tmux-pilot

A thin, opinionated CLI for managing tmux sessions, task worktrees, and PR metadata for AI coding agents (Claude Code, Codex, etc).

**Why?** When you run multiple AI coding agents in parallel — each in its own tmux session and often each in its own git worktree — you need a way to bootstrap task branches, list active sessions, peek at output, send follow-up instructions, refresh PR state, and clean up once the branch lands. `tmux-pilot` wraps the fiddly tmux and git conventions into a single `tp` command designed for both humans and AI orchestrators.

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
# tmux-pilot runs: pi --offline --no-extensions --no-skills --no-prompt-templates --no-themes --session-dir ~/repos/pi-mono/.tmux-pilot/pi/sessions
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

# Refresh PR/review metadata, then show a compact dashboard
tp refresh --repo myapp
tp ls --cols NAME,PR,STATUS,DIR

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

The published documentation site is intended to live at <https://cmungall.github.io/tmux-pilot/>.

Detailed documentation also lives under [`docs/`](./docs/overview.md) and is organized using Diataxis:

- overview: [`docs/overview.md`](./docs/overview.md)
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
tp ls --all-metadata           # append known metadata columns
tp ls --cols NAME,PR,DIR       # compact PR dashboard
tp ls --json --status active   # combine filters with JSON
```

`PR` is a compact summary column. It starts with the PR number, then appends short review/merge codes when available:

- `M`: merged
- `X`: closed
- `A`: approved
- `CR`: changes requested
- `RR`: review required
- `P`: pending review state
- `D`: dirty/conflicted
- `B`: blocked
- `C`: clean

Examples: `1548 RR D`, `1553 CR`, `1547 M`.

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

# Launches `pi --offline --no-extensions --no-skills --no-prompt-templates --no-themes --session-dir ~/repos/pi-mono/.tmux-pilot/pi/sessions`
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
- `pi`: `pi --offline --no-extensions --no-skills --no-prompt-templates --no-themes --session-dir {worktree}/.tmux-pilot/pi/sessions`

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
# Explicit in-place launch using the built-in Codex profile.
tp new rename-types --profile codex -c ~/repos/myapp

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

Shows process, PID, working directory, all metadata, relative freshness for cached metadata, and the last 5 lines of scrollback.

```bash
tp status NAME
```

PR-related metadata is shown with refresh ages when available, for example:

```text
@pr = 1548 (updated 2m ago)
@pr_review = REVIEW_REQUIRED (updated 2m ago)
@pr_merge_state = DIRTY (updated 2m ago)
@last_refresh = 2026-04-19T22:39:42.658Z
```

### `tp refresh` — Refresh PR metadata without reaping

Use this when you want a review dashboard or fresh PR metadata without any destructive cleanup.

```bash
tp refresh                      # all sessions
tp refresh docs-pass            # one named session
tp refresh --repo myapp         # repo-scoped subset
tp refresh --json               # machine-readable output
```

`tp refresh` updates `@pr`, `@pr_state`, `@pr_review`, `@pr_merge_state`, and `@last_refresh` in tmux metadata. It does not kill sessions, remove worktrees, or delete branches.

### `tp set` / `tp get` — Session metadata

Metadata is stored as tmux user options (`@`-prefixed). Common built-in keys include `repo`, `task`, `desc`, `status`, `origin`, `branch`, `needs`, `last_send`, `pr`, `pr_state`, `pr_review`, `pr_merge_state`, and `last_refresh`.

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
# Refresh review state for a repo
tp refresh --repo myapp

# See which branches need attention
tp ls --cols NAME,PR,STATUS,DIR --repo myapp

# Drill into the sessions that need work
tp ls --json --repo myapp | jq -r '.[] | select(.metadata.pr_review == "CHANGES_REQUESTED") | .name' | while read name; do
  tp peek "$name" -n 20
  tp send --wait "$name" "address the requested review changes"
done
```

## Key Features

- **Zero dependencies** — stdlib only (subprocess calls to tmux)
- **Process detection** — distinguishes claude-code vs codex vs bare shell
- **Task bootstrap** — create task branches and worktrees directly from `tp new --repo`
- **PR refresh** — cache PR number, state, review state, and merge state with `tp refresh`
- **Metadata** — tmux user options (@status, @desc, @repo, @branch, @pr, etc.)
- **Metadata freshness** — `tp status` shows when cached fields were last updated
- **Peek without attaching** — critical for orchestrators monitoring sessions
- **JSON output** — `tp ls --json` for machine-readable session data
- **Filtering** — `tp ls --status/--repo/--process` and `tp refresh --repo` to narrow results
- **fzf integration** — optional fuzzy picker for `tp jump`

## License

MIT
