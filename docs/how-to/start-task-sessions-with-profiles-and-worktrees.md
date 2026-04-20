# Start Task Sessions With Profiles And Worktrees

Use `tp new` when you want one command to prepare a task workspace and launch an agent inside it.

## Start In Place

Launch an agent profile directly in an existing directory. These examples show the exact agent command that `tp` starts inside tmux:

```bash
# Runs: codex --profile yolo
tp new docs-pass --profile codex -c ~/repos/tmux-pilot

# Runs: claude --permission-mode bypassPermissions
tp new review-pass --profile claude -c ~/repos/myapp

# Runs: pi --offline --no-extensions --no-skills --no-prompt-templates --no-themes --session-dir ~/repos/pi-mono/.tmux-pilot/pi/sessions
tp new pi-local --profile pi -c ~/repos/pi-mono
```

Built-in profiles:

- `codex` -> `codex --profile yolo`
- `claude` -> `claude --permission-mode bypassPermissions`
- `pi` -> `pi --offline --no-extensions --no-skills --no-prompt-templates --no-themes --session-dir {worktree}/.tmux-pilot/pi/sessions`

## Bootstrap A Task Repo

Point `--repo` at either a local checkout or a GitHub repository.

Example: bootstrap from a local checkout:

```bash
tp new auth-fix --profile codex --repo ~/repos/myapp
```

With the default settings, that command:

1. Resolves or clones the repo.
2. Derives branch `feat/auth-fix`.
3. Creates worktree `~/worktrees/myapp-auth-fix`.
4. Starts `codex --profile yolo` in that worktree.

Issue-driven example:

```bash
tp new issue-771 --profile claude --repo ~/repos/myapp --issue 771
```

That command derives branch `fix/771-issue-771`, fetches the issue title into `@desc`, and launches `claude --permission-mode bypassPermissions` in the new worktree.

GitHub bootstrap example:

```bash
tp new pi-smoke --profile pi --repo badlogic/pi-mono
```

If `~/repos/pi-mono` does not exist yet, `tp` clones it first. Then it creates worktree `~/worktrees/pi-mono-pi-smoke`, derives branch `feat/pi-smoke`, and launches:

```bash
pi --offline --no-extensions --no-skills --no-prompt-templates --no-themes --session-dir ~/worktrees/pi-mono-pi-smoke/.tmux-pilot/pi/sessions
```

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
extends = "pi"
branch_prefix = "task"

[profiles.myapp]
extends = "codex"
repo = "~/repos/myapp"
branch_prefix = "feat"
base_ref = "origin/main"
```

`extends` can reference either another configured profile or a built-in profile.

Concrete config-driven examples:

```bash
# Explicit in-place launch using the built-in Codex profile.
tp new rename-types --profile codex -c ~/repos/myapp

# Uses repo/base_ref from `[profiles.myapp]`, so `--repo` is optional.
tp new api-cleanup --profile myapp

# Uses the customized Pi profile, so the branch is `task/pi-smoke`.
tp new pi-smoke --profile pi --repo badlogic/pi-mono
```
