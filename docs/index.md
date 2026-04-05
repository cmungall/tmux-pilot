---
hide:
  - toc
---

<div class="hero" markdown="1">

<p class="hero-eyebrow">tmux-pilot documentation</p>

# Run Codex, Claude Code, and Pi in tmux without losing the thread.

`tmux-pilot` gives you one operational CLI for starting agent sessions, bootstrapping task worktrees, peeking at live output, sending follow-up instructions, and cleaning up after the branch lands.

<div class="hero-actions" markdown="1">

[Install and quickstart](getting-started.md){ .md-button .md-button--primary }
[CLI cookbook](cli-cookbook.md){ .md-button }
[Command reference](reference/cli-reference.md){ .md-button }

</div>
</div>

<div class="command-band" markdown="1">

<div class="command-tile" markdown="1">
<span class="command-label">Launch in an existing checkout</span>

```bash
tp new docs-pass --profile codex -c ~/repos/tmux-pilot
```

</div>

<div class="command-tile" markdown="1">
<span class="command-label">Bootstrap a task worktree</span>

```bash
tp new auth-fix --profile claude --repo ~/repos/myapp --issue 771
```

</div>

<div class="command-tile" markdown="1">
<span class="command-label">Send the next instruction safely</span>

```bash
tp send --wait docs-pass "add tests for the OAuth callback"
```

</div>

</div>

## What You Actually Do With `tp`

=== "Start agents fast"

    ```bash
    tp new docs-pass --profile codex -c ~/repos/tmux-pilot
    tp new review-pass --profile claude -c ~/repos/myapp
    tp new pi-local --profile pi -c ~/repos/pi-mono
    ```

=== "Bootstrap a real task branch"

    ```bash
    tp new oauth-fix --profile codex --repo ~/repos/myapp
    tp new issue-771 --profile claude --repo ~/repos/myapp --issue 771
    tp new pi-smoke --profile pi --repo badlogic/pi-mono
    ```

=== "Steer a long-lived session"

    ```bash
    tp ls --status active
    tp peek docs-pass -n 50
    tp send --wait docs-pass "continue with regression coverage"
    tp status docs-pass
    ```

## Built For CLI-Heavy Work

<div class="grid cards" markdown="1">

-   **Concrete examples first**

    The docs lead with commands you can paste directly into a shell, not abstract architecture diagrams.

-   **Profiles for the common agents**

    Built-in launch profiles cover Codex, Claude Code, and Pi, and custom profiles let you codify repo-specific defaults.

-   **Task bootstrap included**

    `tp new --repo ...` can resolve or clone a repo, derive a task branch, create a worktree, and launch the agent there.

-   **Steering without attaching**

    `tp ls`, `tp peek`, `tp send --wait`, and `tp status` let you manage live sessions from another terminal.

</div>

## Start With One Of These Pages

<div class="grid cards" markdown="1">

-   **[Install and Quickstart](getting-started.md)**

    Get `tp` installed and run your first Codex, Claude Code, or Pi session in a few commands.

-   **[CLI Cookbook](cli-cookbook.md)**

    Find copy-paste examples for common flows: listing sessions, sending follow-ups, bootstrapping worktrees, cleaning up, and reaping merged branches.

-   **[Profiles and Worktrees](how-to/start-task-sessions-with-profiles-and-worktrees.md)**

    See the exact CLI flows for reusable profiles and repo-backed task sessions.

-   **[CLI Reference](reference/cli-reference.md)**

    Keep a compact command-by-command reference open in another tab while you work.

</div>

## Why The Site Is Structured This Way

The emphasis here is intentionally narrow:

- the **CLI guides** show real shell commands and workflows
- the **concept pages** explain how readiness and transcript-backed state work
- the **reference** section stays compact, with Python automation treated as a small secondary surface

<p class="mini-note">If you only read one thing before trying `tp`, read <a href="getting-started.md">Install and Quickstart</a>.</p>
