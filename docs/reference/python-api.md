# Python API

`tmux-pilot` is a CLI-first project. The `tp` command is the interface to prefer for long-lived automation, shell workflows, and cross-tool orchestration.

The Python modules are still useful for local scripting, but they are a smaller surface and may evolve faster than the CLI.

## What Is Public Enough To Use

The most practical import points today are:

- `tmux_pilot.__version__`
- `tmux_pilot.core`
- `tmux_pilot.hooks`
- `tmux_pilot.reaper`

## Package Version

```python
from tmux_pilot import __version__

print(__version__)
```

## List Sessions

```python
from tmux_pilot import core

sessions = core.list_sessions(status="active", process="codex")
for session in sessions:
    print(session.name, session.process, session.metadata.get("branch", ""))
```

## Create And Drive A Session

```python
from tmux_pilot import core

core.new_session("docs-pass", directory="/Users/me/repos/tmux-pilot")
core.launch_agent_session(
    "docs-pass",
    "codex --profile yolo --no-alt-screen",
    prompt="summarize the docs structure",
    expected_cwd="/Users/me/repos/tmux-pilot",
)

core.send_text(
    "docs-pass",
    "now add a CLI examples page",
    wait=True,
    timeout=90,
)

status = core.get_session_status("docs-pass")
print(status["agent"])
```

Useful `core` helpers for automation:

- `list_sessions(...)`
- `new_session(...)`
- `launch_agent_session(...)`
- `send_text(...)`
- `create_profile_session(...)`
- `wait_until_session_ready(...)`
- `get_session_status(...)`
- `get_session_trace(...)`
- `kill_session(...)`

## Install Or Remove Git Hooks

```python
from pathlib import Path
from tmux_pilot import hooks

result = hooks.install_hooks(Path.home() / ".config/git/hooks")
print(result)

result = hooks.uninstall_hooks()
print(result)
```

## Reap Merged Sessions

```python
from tmux_pilot import reaper

result = reaper.reap_sessions(dry_run=True)
print(result)
```

## Refresh Cached PR Metadata

```python
from tmux_pilot import reaper

result = reaper.refresh_pr_metadata(repo="myapp")
print(result)
```

## Inspect A Session Trace

```python
from tmux_pilot import core

trace = core.get_session_trace("docs-pass", refresh=False, lines=5)
print(trace["agent"], trace["path"])
```

## Recommendation

If the workflow needs to survive shell boundaries, CI jobs, or multiple languages, prefer the CLI:

```bash
tp ls --json
tp send --wait docs-pass "continue with the next step"
```

If the workflow is entirely local and Python-native, the module APIs above are the most useful entry points.
