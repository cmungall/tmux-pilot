# Start Task Sessions With Profiles And Worktrees

Use `tp new` when you want one command to prepare a task workspace and launch an agent inside it.

## Start In Place

Launch an agent profile directly in an existing directory:

```bash
tp new docs-pass --profile codex -c ~/repos/tmux-pilot
tp new review-pass --profile claude -c ~/repos/myapp
tp new pi-local --profile pi -c ~/repos/pi-mono
```

Built-in profiles:

- `codex` -> `codex --profile yolo`
- `claude` -> `claude --permission-mode bypassPermissions`
- `pi` -> `pi --session-dir {worktree}/.tmux-pilot/pi/sessions`

## Bootstrap A Task Repo

Point `--repo` at either a local checkout or a GitHub repository:

```bash
tp new auth-fix --profile codex --repo ~/repos/myapp
tp new issue-771 --profile claude --repo ~/repos/myapp --issue 771
tp new pi-smoke --profile pi --repo badlogic/pi-mono
```

That flow:

1. Resolves or clones the repo.
2. Derives a branch from the session name or issue number.
3. Creates a worktree under the configured worktree base.
4. Starts the selected agent in that worktree.

Override the branch or base ref when needed:

```bash
tp new cleanup --profile codex --repo ~/repos/myapp --branch chore/cleanup
tp new backport --profile codex --repo ~/repos/myapp --base-ref origin/release/1.2
```

## Configure Reusable Profiles

Create `~/.config/tmux-pilot/profiles.toml`:

```toml
[default]
extends = "codex"
worktree_base = "~/worktrees"
clone_base = "~/repos"

[profiles.pi]
branch_prefix = "task"

[profiles.myapp]
extends = "claude"
repo = "~/repos/myapp"
branch_prefix = "feat"
base_ref = "origin/main"
```

`extends` can reference either another configured profile or a built-in profile.
