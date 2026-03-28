"""Git hook installation for tmux-pilot session lifecycle."""

from __future__ import annotations

import subprocess
from pathlib import Path

DEFAULT_HOOKS_DIR = Path.home() / ".config" / "git" / "hooks"

# Marker so we can identify our hooks
_MARKER = "# tmux-pilot managed hook"

_POST_COMMIT = f"""\
#!/bin/sh
{_MARKER}
# Updates @branch and @last_commit on the current tmux session.

if [ -n "$TMUX" ] && command -v tp >/dev/null 2>&1; then
    _session=$(tmux display-message -p '#S')
    _branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
    _commit=$(git rev-parse --short HEAD 2>/dev/null)
    tp set "$_session" branch "$_branch" 2>/dev/null
    tp set "$_session" last_commit "$_commit" 2>/dev/null
fi

# Chain with previous hook
_chain="$(dirname "$0")/post-commit.pre-tp"
[ -x "$_chain" ] && exec "$_chain" "$@"
"""

_POST_CHECKOUT = f"""\
#!/bin/sh
{_MARKER}
# Updates @branch on the current tmux session.

if [ -n "$TMUX" ] && command -v tp >/dev/null 2>&1; then
    _session=$(tmux display-message -p '#S')
    _branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
    tp set "$_session" branch "$_branch" 2>/dev/null
fi

# Chain with previous hook
_chain="$(dirname "$0")/post-checkout.pre-tp"
[ -x "$_chain" ] && exec "$_chain" "$@"
"""

_PRE_PUSH = f"""\
#!/bin/sh
{_MARKER}
# Sets @pushing=true on the current tmux session.

if [ -n "$TMUX" ] && command -v tp >/dev/null 2>&1; then
    _session=$(tmux display-message -p '#S')
    tp set "$_session" pushing true 2>/dev/null
fi

# Chain with previous hook
_chain="$(dirname "$0")/pre-push.pre-tp"
[ -x "$_chain" ] && exec "$_chain" "$@"
"""

HOOKS: dict[str, str] = {
    "post-commit": _POST_COMMIT,
    "post-checkout": _POST_CHECKOUT,
    "pre-push": _PRE_PUSH,
}

_SAVED_PATH_FILE = ".tp-previous-hookspath"


def _get_hooks_path_config() -> str:
    """Get the current global core.hooksPath, or empty string."""
    result = subprocess.run(
        ["git", "config", "--global", "core.hooksPath"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _set_hooks_path_config(path: str) -> None:
    """Set global core.hooksPath."""
    subprocess.run(
        ["git", "config", "--global", "core.hooksPath", path],
        check=True, capture_output=True, text=True,
    )


def _unset_hooks_path_config() -> None:
    """Unset global core.hooksPath."""
    subprocess.run(
        ["git", "config", "--global", "--unset", "core.hooksPath"],
        capture_output=True, text=True,
    )


def _is_tp_hook(path: Path) -> bool:
    """Check if a hook file was written by tmux-pilot."""
    if not path.is_file():
        return False
    return _MARKER in path.read_text()


def install_hooks(hooks_dir: Path | None = None) -> dict:
    """Install git hooks and configure core.hooksPath.

    Returns dict with keys: hooks_installed, hooks_dir.
    """
    hdir = hooks_dir or DEFAULT_HOOKS_DIR
    hdir.mkdir(parents=True, exist_ok=True)

    # Save previous core.hooksPath so we can restore on uninstall
    previous = _get_hooks_path_config()
    if previous and str(Path(previous).resolve()) != str(hdir.resolve()):
        (hdir / _SAVED_PATH_FILE).write_text(previous)

    installed = []
    for name, content in HOOKS.items():
        hook_path = hdir / name
        # If there's an existing non-tp hook, preserve it for chaining
        if hook_path.is_file() and not _is_tp_hook(hook_path):
            chain_path = hdir / f"{name}.pre-tp"
            hook_path.rename(chain_path)
        hook_path.write_text(content)
        hook_path.chmod(0o755)
        installed.append(name)

    _set_hooks_path_config(str(hdir))

    return {
        "hooks_installed": installed,
        "hooks_dir": str(hdir),
    }


def uninstall_hooks(hooks_dir: Path | None = None) -> dict:
    """Remove tmux-pilot hooks and restore previous core.hooksPath.

    Returns dict with keys: hooks_removed, restored_hooks_path.
    """
    hdir = hooks_dir or DEFAULT_HOOKS_DIR
    removed = []
    for name in HOOKS:
        hook_path = hdir / name
        if hook_path.is_file() and _is_tp_hook(hook_path):
            hook_path.unlink()
            removed.append(name)
            # Restore chained hook if it exists
            chain_path = hdir / f"{name}.pre-tp"
            if chain_path.is_file():
                chain_path.rename(hook_path)

    # Restore previous core.hooksPath
    saved_file = hdir / _SAVED_PATH_FILE
    restored = ""
    if saved_file.is_file():
        restored = saved_file.read_text().strip()
        saved_file.unlink()
        if restored:
            _set_hooks_path_config(restored)
        else:
            _unset_hooks_path_config()
    else:
        _unset_hooks_path_config()

    return {
        "hooks_removed": removed,
        "restored_hooks_path": restored,
    }
