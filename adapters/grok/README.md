# Grok CLI adapter

Bridges Grok CLI's UserPromptSubmit hook to the Kairos ambient injectors
(Layer 1 timestamp, temporal-state, routing, obligations, staleness).

## The three Grok problems this solves

1. **History**: Grok writes no transcripts under `~/.claude/projects`, so the
   default transcript backend classifies every prompt as
   `phase=session-start`; worse, within the transcript-idle window the
   newest-mtime fallback could steal a CONCURRENT Claude session's transcript
   and report Claude's cadence as Grok's. The adapter selects the thread-ring
   backend, and since v0.8.0 the mtime fallback itself requires a Claude
   session identity (env or payload) before it fires.
2. **Thread identity**: Grok uses camelCase `sessionId` (and
   `GROK_SESSION_ID` in env); `resolve_thread_id()` and `time.sh` accept both
   since v0.8.0, and the adapter normalizes the bridged payload to
   `session_id` anyway.
3. **Injection**: Grok treats plain UserPromptSubmit stdout as observe-only,
   so the adapter emits the collected injector lines as the Claude hook JSON
   contract instead:

   ```json
   {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                           "additionalContext": "[temporal-state] ..."}}
   ```

   Live-verified on Grok CLI (2026-08-18): UserPromptSubmit is observe-only.
   Grok ignores the exit code and stdout, including the Claude
   `hookSpecificOutput.additionalContext` JSON this adapter emits. The
   injectors still run and the ring still records, so history and identity are
   correct. The model never sees `[temporal-state]` / `[obligations]` /
   `[staleness]` as ambient context.

   `additionalContext` is only documented on Stop, where it means "keep the
   agent working" rather than "inject into the prompt." Do not use Stop as the
   injection path.

   This is a Grok product gap, not a Kairos failure. Layers 3/4/5 stay
   pull-available over MCP. The moment Grok delivers UserPromptSubmit
   additionalContext to the model, this adapter starts injecting with no
   further change.

   Verify on a live session by asking the model to repeat any
   `[temporal-state]` line it can see in its context.

Hooks stay read-only; the adapter records the prompt timestamp exactly once
per prompt, after the hook chain, same contract as the Codex adapter.

## Install

1. Make sure the Kairos hooks are installed (default `~/.claude/hooks`).
2. Copy `kairos-user-prompt.py` into Grok's hook directory.
3. Register it for UserPromptSubmit in Grok's hook configuration (Claude
   settings.json shape, adjust to where your Grok build reads hooks):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/usr/bin/python3 /home/USER/.grok/hooks/kairos-user-prompt.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

4. Disable any raw (non-adapter) Kairos hook wiring for Grok at the same
   time, otherwise the chain runs twice per prompt.

## Env knobs

Same as the Codex adapter: `KAIROS_HOOKS_DIR`, `CLAUDE_KIT_STATE_DIR`,
`KAIROS_RING_STALE_SECONDS`. DB paths and preferences come from
`~/.config/kairos/config.json` (`memory_db`, `tasks_db`, `future_inject`,
...), read by the hooks themselves; env `KAIROS_*` overrides per knob.

## Expected behavior

- First prompt in a new Grok session: `phase=session-start`
- Next prompt ~2 min later: `cadence=active-collaboration | phase=continuing`
- A concurrent Claude session's transcript is never inherited
- Sessions are isolated (per-thread rings; `time.sh` date markers keyed by
  thread id, not a shared "default")
- Optional: include ring timestamps in temporal-pattern analytics with
  `KAIROS_PATTERN_SOURCES=transcripts,ring`

## Turn-end timing (0.12.0)

Without a reply timestamp the hooks measure the gap prompt-to-prompt and
label cadence `(turn-basis)`. If this harness exposes a turn-end (Stop)
event, run `hooks/turn-end.py` on it with `KAIROS_HISTORY_BACKEND=ring` and
the same thread id the prompt adapter uses; cadence then classifies on the
user's own pause and the label switches to `since-reply`.
