# Codex CLI adapter

Bridges Codex CLI's UserPromptSubmit hook to the Kairos ambient injectors
(Layer 1 timestamp, temporal-state, routing, obligations, staleness).

Codex writes no transcripts under `~/.claude/projects`, so the transcript
history backend cannot see Codex prompts; without this adapter every prompt
classifies as `phase=session-start`. The adapter selects the thread-ring
backend (`KAIROS_HISTORY_BACKEND=ring`): prompt timestamps are kept per
thread id in small JSON rings under `<state dir>/thread-rings/`, hashed
filenames, capped at 20 entries, stale rings pruned after 30 days.

Hooks stay read-only; the adapter records the prompt timestamp exactly once
per prompt, after the hook chain has run, so every hook in the chain sees the
same prior state.

## Install

1. Make sure the Kairos hooks are installed (default `~/.claude/hooks`).
2. Copy `kairos-user-prompt.py` to `~/.codex/hooks/`.
3. Register it in `~/.codex/hooks.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/usr/bin/python3 /home/USER/.codex/hooks/kairos-user-prompt.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

4. Codex gates hooks behind trust; approve the hook on first use (or manage
   `[hooks.state]` in `~/.codex/config.toml`).

## Env knobs

All optional; set them by wrapping the command in `hooks.json` with `env`,
e.g. `env KAIROS_TASKS_DB=/srv/tasks.db /usr/bin/python3 ...`.

| Var | Default | Purpose |
|---|---|---|
| `KAIROS_HOOKS_DIR` | `~/.claude/hooks` | where the Kairos hook scripts live |
| `CLAUDE_KIT_STATE_DIR` | `~/.claude/state` | kit state dir (rings live under `thread-rings/`) |
| `KAIROS_MEMORY_DB` | resolved by the hooks: config `memory_db`, then `MNEMOS_DB`, then `~/work/memory.db` if it exists, else `~/.mnemos/memory.db` | Mnemos db for the obligations line; set `memory_db` in `~/.config/kairos/config.json` |
| `KAIROS_TASKS_DB` | config `tasks_db`, else `~/work/tasks.db` | tasks db for the obligations line |
| `KAIROS_RING_STALE_SECONDS` | 30 days | prune threshold for abandoned rings |

## Expected behavior

- First prompt in a new Codex thread: `phase=session-start`
- Next prompt ~2 min later: `cadence=active-collaboration | phase=continuing`
- Separate threads are isolated (per-thread rings)
- Long gaps and cross-day gaps classify exactly as in Claude Code
- Corrupt or missing ring state degrades to session-start, never crashes

## Turn-end timing (0.12.0)

Without a reply timestamp the hooks measure the gap prompt-to-prompt and
label cadence `(turn-basis)`. If this harness exposes a turn-end (Stop)
event, run `hooks/turn-end.py` on it with `KAIROS_HISTORY_BACKEND=ring` and
the same thread id the prompt adapter uses; cadence then classifies on the
user's own pause and the label switches to `since-reply`.
