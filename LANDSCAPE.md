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

## opensessions (github.com/Ataraxy-Labs/opensessions)

**What:** tmux sidebar plugin (via TPM) with live agent state detection, HTTP metadata API, and session switching TUI.

**Key ideas worth stealing:**

### 1. Agent file watchers (not pane scraping)
Reads agent session files directly:
- Claude Code: JSONL transcripts in `~/.claude/projects/`
- Codex: JSONL in `~/.codex/sessions/` (resolves session from `turn_context.cwd`)
- Amp: `~/.local/share/amp/threads/*.json`
- OpenCode: SQLite in `~/.local/share/opencode/opencode.db`

This is vastly more reliable than our current pane-output heuristics in `plugins/agents/`.

### 2. HTTP metadata API (localhost:7391)
Any script/agent can push status via curl — no tmux dependency:
```bash
curl -X POST http://127.0.0.1:7391/set-status \
  -d '{"session":"my-app","text":"Deploying","tone":"warn"}'
curl -X POST http://127.0.0.1:7391/set-progress \
  -d '{"session":"my-app","current":3,"total":10,"label":"diseases"}'
curl -X POST http://127.0.0.1:7391/log \
  -d '{"session":"my-app","message":"Tests passed","tone":"success"}'
```
Endpoints: `/set-status`, `/set-progress`, `/log`, `/clear-log`, `/notify`
Tones: neutral, info, success, warn, error

### 3. Progress tracking
`current/total` progress bars — exactly what we need for batch jobs (prevalence batches, gene reviews).

**Architecture:**
- Bun workspace (TypeScript)
- Local server on 127.0.0.1:7391
- TUI sidebar built with Solid (OpenTUI)
- TPM plugin integration
- Hidden sidebars stashed in `_os_stash` tmux session

**Comparison with tp + SwiftMux:**

| | opensessions | tp + SwiftMux |
|---|---|---|
| UI | tmux sidebar pane (TUI) | Native macOS app (GUI) |
| Agent detection | Reads session files directly | Pane output heuristics |
| Metadata API | HTTP on localhost:7391 | tmux @vars |
| Session lifecycle | Manual | tp reap (PR-driven) |
| Profiles/templates | No | tp new --profile |
| Git integration | Shows branch | hooks + reap + PR state |
| Dependencies | bun + TPM | Python (tp), Swift (SwiftMux) |

**Not worth adopting wholesale:**
- Requires bun runtime
- No session lifecycle management (no equivalent of tp reap)
- No profile/template system
- No git hook integration

**Source:** https://github.com/Ataraxy-Labs/opensessions
