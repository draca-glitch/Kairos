#!/usr/bin/env python3
"""
UserPromptSubmit hook: emit a one-line temporal-state summary so Claude
arrives at the prompt with computed temporal context already grounded.

Sibling to hooks/time.sh, time.sh gives raw timestamp, temporal-state
gives the *shape* of time: gap-since-last, cross-day status, time-of-day
bucket, input-cadence, session-phase.

Output format (single line, low-token):
  [temporal-state] gap=40s(since-reply) | turn=15m | cross-day=no | now=Mon_08:00_CEST(early-morning) | cadence=active-collaboration | phase=continuing

gap is the user's own pause, measured from the assistant's last reply when
that timestamp exists (label since-reply) and otherwise from the previous
prompt (label since-prompt). turn is the raw prompt-to-prompt time and is
shown only when it differs in kind from gap. cadence is an inference from
gap; when gap could only be measured prompt-to-prompt it carries
(turn-basis), because a long "reflective" pause may be the assistant's own
tool time rather than the user thinking.

Logic lives in temporal_lib.py, this hook is just the renderer.

Usage in settings.json:
  "UserPromptSubmit": [{
    "hooks": [{ "type": "command", "command": "~/.claude/hooks/temporal-state.py", "timeout": 2000 }]
  }]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from temporal_lib import compute_state, is_task_notification, parse_payload


def main() -> int:
    payload = parse_payload(sys.stdin.read())
    if is_task_notification(payload):
        return 0

    state = compute_state(payload)

    if not state["transcript_available"]:
        print(f"[temporal-state] now={state['now_str']}({state['tod']}) | phase=session-start | transcript=unavailable")
        return 0

    if state["prompts_count"] == 0:
        print(f"[temporal-state] now={state['now_str']}({state['tod']}) | phase=session-start")
        return 0

    print(render_line(state))
    return 0


def render_line(state: dict) -> str:
    basis = state.get("gap_basis")
    parts = [f"gap={state['gap_str']}({'since-reply' if basis == 'reply' else 'since-prompt'})"]
    if basis == "reply":
        parts.append(f"turn={state['turn_gap_str']}")
    cadence = state["cadence"]
    if basis == "turn":
        cadence += "(turn-basis)"
    parts += [
        f"cross-day={'yes' if state['cross_day'] else 'no'}",
        f"now={state['now_str']}({state['tod']})",
        f"cadence={cadence}",
        f"phase={state['phase']}",
    ]
    return "[temporal-state] " + " | ".join(parts)


if __name__ == "__main__":
    sys.exit(main())
