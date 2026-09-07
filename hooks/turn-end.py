#!/usr/bin/env python3
"""
Turn-end hook (Claude Code calls this event Stop): record when the assistant
finished replying, so the next prompt's gap can be measured from the user's
side instead of prompt-to-prompt.

Claude Code needs none of this: its transcripts stamp every assistant record
and temporal_lib reads them directly. Harnesses on the thread-ring backend
(Codex, Grok, anything using adapters/) have no transcript, so without this
hook their cadence is classified on prompt-to-prompt time and labelled
(turn-basis). Register it on the harness's turn-end event with
KAIROS_HISTORY_BACKEND=ring and the same thread id the prompt adapter uses;
it is a no-op on the transcript backend. Never prints, never raises.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from temporal_lib import history_backend, parse_payload, resolve_thread_id, ring_record_reply


def main() -> int:
    try:
        payload = parse_payload(sys.stdin.read())
        if history_backend() != "ring":
            return 0
        ring_record_reply(resolve_thread_id(payload))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
