# Install and Quickstart

Use this page when you want to get `tp` working quickly and start real agent sessions without hunting through every command flag first.

## Requirements

- Python 3.10+
- `tmux`
- optional: `fzf` for the interactive `tp jump` picker

## Install

=== "uv"

    ```bash
    uv tool install tmux-pilot
    ```

=== "pipx"

    ```bash
    pipx install tmux-pilot
    ```

=== "pip"

    ```bash
    pip install tmux-pilot
    ```

Check that the CLI is available:

```bash
tp --version
tp --help
```

## First Five Commands

If you already have a repo checked out locally, this is the shortest useful path:

```bash
tp new docs-pass --profile codex -c ~/repos/tmux-pilot
tp ls
tp peek docs-pass -n 40
tp send --wait docs-pass "summarize the current docs structure"
tp status docs-pass
```

That flow:

1. creates a tmux session rooted at the repo
2. launches Codex in that session
3. lets you inspect output without attaching
4. waits for the prompt to return before sending the next instruction

## Choose Your Startup Pattern

### 1. Bare tmux session

Use this when you want `tp` to manage the tmux session, but you do not want profile or worktree behavior yet.

```bash
tp new scratch
tp new scratch -c ~/repos/myapp
tp new scratch --here
```

### 2. Launch an agent in an existing checkout

Use this when you already have the repo open where you want to work.

```bash
tp new docs-pass --profile codex -c ~/repos/tmux-pilot
tp new review-pass --profile claude -c ~/repos/myapp
tp new pi-local --profile pi -c ~/repos/pi-mono
```

Exact built-in launch commands:

- `codex` -> `codex --profile yolo`
- `claude` -> `claude --permission-mode bypassPermissions`
- `pi` -> `pi --offline --no-extensions --no-skills --no-prompt-templates --no-themes --session-dir {worktree}/.tmux-pilot/pi/sessions`

### 3. Bootstrap a task branch and worktree

Use this when you want `tp new` to do the repo prep and agent launch in one step.

```bash
tp new oauth-fix --profile codex --repo ~/repos/myapp
tp new issue-771 --profile claude --repo ~/repos/myapp --issue 771
tp new pi-smoke --profile pi --repo badlogic/pi-mono
```

What happens on the bootstrap path:

- `tp` resolves or clones the repo
- derives a branch from the task name or issue
- creates a git worktree under the configured worktree base
- starts the chosen agent inside that worktree

## The Commands You Keep Reusing

```bash
tp ls
tp ls --status active
tp refresh --repo tmux-pilot
tp ls --cols NAME,PR,STATUS,DIR --repo tmux-pilot
tp ls --all-metadata --repo tmux-pilot
tp peek docs-pass -n 60
tp send --wait docs-pass "continue with the failing tests"
tp status docs-pass
tp jump docs-pass
tp kill docs-pass
```

Use `tp refresh` before `tp ls` when you want a current review dashboard. The compact `PR` column folds together the PR number plus short review/merge codes such as `A`, `CR`, `RR`, `D`, and `C`.

When you want the next follow-up prompt to be driven by cached PR state instead of hand-written each time, use `tp prod --dry-run` to preview the configured prod rules and `tp prod` to send them.

## Minimal Profile Config

Create `~/.config/tmux-pilot/profiles.toml` when you want reusable defaults:

```toml
[default]
extends = "codex"
worktree_base = "~/worktrees"
clone_base = "~/repos"

[profiles.myapp]
extends = "claude"
repo = "~/repos/myapp"
branch_prefix = "fix"
base_ref = "origin/main"

[prod]
[[prod.rules]]
name = "changes-requested"
match = { pr_review = "CHANGES_REQUESTED", pr_state = "OPEN" }
prompt = "Address all requested review comments on {pr_display}, update tests as needed, and push the fixes."
```

Concrete examples:

```bash
# Explicit in-place launch in an existing checkout
tp new review-pass --profile claude -c ~/repos/myapp

# Use repo/bootstrap defaults from [profiles.myapp]
tp new issue-771 --profile myapp --issue 771

# Preview or send the next prod prompt based on cached PR state
tp prod --dry-run --repo myapp
tp prod --repo myapp
```

## Local Docs Preview

If you are working on the docs site itself:

```bash
uv sync --group docs
uv run --group docs mkdocs serve
```

That starts a live preview server for the GitHub Pages site.
