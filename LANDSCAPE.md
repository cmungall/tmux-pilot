# Landscape: tmux-based agent session tools

Notes on related tools evaluated for tmux-pilot. See also issue #4.

## smux (github.com/ShawnPana/smux)

**What:** One-command tmux setup with `tmux-bridge` CLI for cross-pane agent communication.

**Key idea:** Agent-to-agent communication via panes. Any agent that can run bash can read/type/send keys to any other pane. Claude Code can prompt Codex in the next pane, and Codex replies back.

**tmux-bridge CLI:**
```
tmux-bridge list                    # show all panes
tmux-bridge read <target> [lines]   # read from a pane
tmux-bridge type <target> <text>    # type into a pane
tmux-bridge keys <target> <key>...  # send keys
tmux-bridge name <target> <label>   # label a pane
```

**Model:** Panes within a single session. Everything on one screen. Option-key bindings (no prefix).

**Comparison with tp:**

| | smux | tp |
|---|---|---|
| Unit | Panes | Sessions |
| Agent comms | tmux-bridge (read/type/keys) | tp send/peek |
| Metadata | Pane labels only | @repo, @branch, @status, @desc, @pr |
| Lifecycle | Manual | tp reap (PR-state driven) |
| Agent-to-agent | Yes — first-class | Not built-in |
| Scaling | 2-3 agents on one screen | 30+ concurrent isolated jobs |
| Skills | skills.sh integration | OpenClaw skills |

**Worth stealing:**
- `tmux-bridge` abstraction — clean CLI for cross-pane IPC
- Agent-to-agent communication pattern
- skills.sh distribution model

**Not worth adopting:**
- Pane-centric model doesn't scale for our 30+ concurrent job workflow
- Option-key bindings conflict with Emacs/macOS conventions
- No metadata, no lifecycle management, no git integration

**Source:** https://github.com/ShawnPana/smux  
**Tweet:** https://x.com/shawn_pana/status/2037760545181536661
