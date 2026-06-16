# Persist And Restore Sessions Across Reboots

Use this guide when you run many tmux sessions (one per repo or worktree, as `tp`
encourages) and want them to survive a reboot or crash — **without** the
interactive lag that `tmux-continuum`'s auto-save causes at that scale.

tmux sessions live only in the tmux server's memory, so a restart loses them.
The setup below restores your sessions automatically on boot while keeping tmux
responsive.

## The approach

Three pieces, each doing one job:

- **[tmux-resurrect](https://github.com/tmux-plugins/tmux-resurrect)** — the
  save/restore format and the restore action.
- **[tmux-continuum](https://github.com/tmux-plugins/tmux-continuum)** — used
  **only** for restore-on-boot. Its in-tmux auto-save is turned off.
- **A scheduler outside tmux** (launchd on macOS) — runs resurrect's save on a
  timer in a detached process, so saving never touches tmux's event loop.

## Why not just let tmux-continuum save

Continuum's auto-save piggybacks on tmux's **status-line refresh**: on every
redraw, for every attached client, it checks whether a save is due and forks
resurrect's `save.sh`, which spawns dozens of `tmux` subprocesses to walk every
session, window, and pane. Because that work runs on tmux's own event loop, it
competes with your typing and redraws. With ~30+ sessions and multiple clients
the saves also overlap — the "thundering herd" spike documented in
[continuum#126](https://github.com/tmux-plugins/tmux-continuum/issues/126).

The fix is not to save less often; it's to run the same save **off** tmux's
event loop. resurrect's `save.sh` is fast on its own (~3s for 30+ sessions once
pane-content capture is off) — continuum's scheduling was the cost, not the save.

## Prerequisites

- [tpm](https://github.com/tmux-plugins/tpm), `tmux-resurrect`, and
  `tmux-continuum` installed.
- macOS for the launchd steps. See [Linux](#linux-systemd-or-cron) below for the
  equivalent.

## 1. Configure tmux

In `~/.tmux.conf`:

```tmux
set -g @plugin 'tmux-plugins/tpm'
set -g @plugin 'tmux-plugins/tmux-resurrect'
set -g @plugin 'tmux-plugins/tmux-continuum'

# Don't capture scrollback: it's the heaviest part of a save and you rarely
# need it back. You still get layout, working dirs, and running commands.
set -g @resurrect-capture-pane-contents 'off'

# Continuum: restore on boot only. Disable its in-tmux auto-save (interval 0),
# which hooks the status line and lags with many sessions (continuum#126).
# Saving is handled by the out-of-tmux scheduler in step 3.
set -g @continuum-restore 'on'
set -g @continuum-save-interval '0'
```

Apply the save-interval change to an already-running server without a restart:

```bash
tmux set -g @continuum-save-interval '0'
```

!!! warning "Don't `source-file` to apply this with restore enabled"
    With `@continuum-restore 'on'`, re-running `tmux source-file ~/.tmux.conf`
    re-runs plugin init and can re-trigger a **restore** into your live server,
    spawning your saved sessions on top of the current ones. Set the single
    option directly (above) instead.

## 2. Add a guarded save script

Create `~/.tmux/resurrect-save-guarded.sh`. It wraps resurrect's `save.sh` with
two guards: skip when there's no server to save (so a fresh boot can't overwrite
a good snapshot with an empty one), and self-heal the `last` pointer if a save is
ever interrupted mid-write.

```bash
#!/bin/bash
# Guarded tmux-resurrect save, driven OUT of tmux by a scheduler.
set -u

TMUX_BIN="$(command -v tmux)"          # or hardcode, e.g. /opt/homebrew/bin/tmux
RES_DIR="$HOME/.tmux/resurrect"
SAVE_SH="$HOME/.tmux/plugins/tmux-resurrect/scripts/save.sh"

# A valid resurrect snapshot has at least one pane line.
is_valid() { grep -q "^pane" "$1" 2>/dev/null; }

# If 'last' isn't a valid snapshot, point it at the newest one that is.
heal_last() {
    local target="$RES_DIR/$(readlink "$RES_DIR/last" 2>/dev/null)"
    is_valid "$target" && return 0
    local f
    for f in $(ls -t "$RES_DIR"/tmux_resurrect_*.txt 2>/dev/null); do
        if is_valid "$f"; then
            ln -sf "$(basename "$f")" "$RES_DIR/last"
            echo "healed 'last' -> $(basename "$f")"
            return 0
        fi
    done
}

heal_last
"$TMUX_BIN" list-sessions >/dev/null 2>&1 || exit 0   # nothing to save
"$SAVE_SH"
heal_last
```

Make it executable:

```bash
chmod +x ~/.tmux/resurrect-save-guarded.sh
```

## 3. Schedule it outside tmux (macOS launchd)

Create `~/Library/LaunchAgents/com.tmux-resurrect-save.plist`. launchd does **not**
expand `~`, so use absolute paths and set a real `PATH` (resurrect's `save.sh`
calls bare `tmux`):

```xml title="~/Library/LaunchAgents/com.tmux-resurrect-save.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tmux-resurrect-save</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/YOU/.tmux/resurrect-save-guarded.sh</string>
    </array>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>

    <key>StartInterval</key>
    <integer>1200</integer>

    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/Users/YOU/Library/Logs/tmux-resurrect-save.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/YOU/Library/Logs/tmux-resurrect-save.log</string>
</dict>
</plist>
```

Replace `/Users/YOU` with your home directory and adjust `StartInterval`
(seconds) to taste. Load it:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.tmux-resurrect-save.plist
```

## 4. Verify

Force a run and confirm a fresh, multi-KB snapshot appears:

```bash
launchctl kickstart -k gui/$(id -u)/com.tmux-resurrect-save
ls -lt ~/.tmux/resurrect/ | head
```

A healthy snapshot is several KB and contains `pane` lines; a truncated one is
~44 bytes. Check that `last` points at a real one:

```bash
last=~/.tmux/resurrect/$(readlink ~/.tmux/resurrect/last)
wc -c "$last"; grep -c '^pane' "$last"
```

!!! note "Verify from a normal terminal"
    Run the verification from your own shell, not from inside an automated agent
    session — some agent harnesses reap the detached job before it finishes,
    leaving a truncated snapshot. The guard script repairs that on the next run,
    but you'll get a clean result faster from a plain terminal.

## Restore

Restore happens automatically the next time the tmux **server** starts (because
`@continuum-restore 'on'`). To restore manually into a running server, use the
resurrect binding:

```text
prefix + Ctrl-r
```

## What gets restored

- Sessions, windows, and pane layout
- Each pane's working directory
- The command that was running in each pane (the program is relaunched)

Scrollback and in-program state are **not** restored — that's the deliberate
trade-off that keeps saves cheap.

## Linux (systemd or cron)

Use the same `resurrect-save-guarded.sh` from step 2, scheduled with a systemd
user timer:

```ini
# ~/.config/systemd/user/tmux-resurrect-save.service
[Service]
Type=oneshot
ExecStart=%h/.tmux/resurrect-save-guarded.sh
```

```ini
# ~/.config/systemd/user/tmux-resurrect-save.timer
[Timer]
OnBootSec=5min
OnUnitActiveSec=20min

[Install]
WantedBy=timers.target
```

```bash
systemctl --user enable --now tmux-resurrect-save.timer
```

Or, more simply, a cron entry running the same script every 20 minutes:

```cron
*/20 * * * * "$HOME/.tmux/resurrect-save-guarded.sh"
```
