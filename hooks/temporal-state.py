#!/usr/bin/env python3
"""
UserPromptSubmit hook: emit a one-line temporal-state summary so Claude
arrives at the prompt with computed temporal context already grounded.

Sibling to hooks/time.sh — time.sh gives raw timestamp, temporal-state
gives the *shape* of time: gap-since-last, cross-day status, time-of-day
bucket, input-cadence, session-phase.

Output format (single line, low-token):
  [temporal-state] gap=11h17m | cross-day=yes | now=02:02_CEST(late-night) | cadence=resumed-after-long-gap | phase=interruption-pivot

Logic lives in temporal_lib.py — this hook is just the renderer.

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

    parts = [
        f"gap={state['gap_str']}",
        f"cross-day={'yes' if state['cross_day'] else 'no'}",
        f"now={state['now_str']}({state['tod']})",
        f"cadence={state['cadence']}",
        f"phase={state['phase']}",
    ]
    print(f"[temporal-state] " + " | ".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
