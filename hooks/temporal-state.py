#!/usr/bin/env python3
"""
UserPromptSubmit hook: emit a one-line temporal-state summary so Claude
arrives at the prompt with computed temporal context already grounded.

Sibling to hooks/time.sh — time.sh gives raw timestamp, temporal-state
gives the *shape* of time: gap-since-last, cross-day status, time-of-day
bucket, input-cadence, session-phase. Run alongside time.sh, not instead.

Filters out task-notification events the same way time.sh does, so
background-task completions don't trigger a spurious refresh.

Reads the current session transcript at
  ~/.claude/projects/-<cwd>/<session_id>.jsonl
parses the last N real user messages, derives the state.

Output format (single line, low-token):
  [temporal-state] gap=11h17m | cross-day=yes | now=02:02_CEST(late-night) | cadence=resumed | phase=interruption-pivot

Usage in settings.json:
  "UserPromptSubmit": [{
    "hooks": [{ "type": "command", "command": "~/.claude/hooks/temporal-state.py", "timeout": 2000 }]
  }]
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def parse_payload(raw: str) -> dict:
    try:
        return json.loads(raw)
    except Exception:
        return {}


def is_task_notification(payload: dict) -> bool:
    prompt = payload.get("prompt") or ""
    return "<task-notification>" in prompt


def find_transcript() -> Path | None:
    """Locate current session JSONL.

    Try CLAUDE_SESSION_ID + cwd-derived project dir; fall back to the
    most-recently-modified .jsonl under ~/.claude/projects/.
    """
    home = Path.home() / ".claude" / "projects"
    if not home.exists():
        return None

    session_id = os.environ.get("CLAUDE_SESSION_ID", "").strip()
    if session_id:
        for jsonl in home.rglob(f"{session_id}.jsonl"):
            return jsonl

    # Fallback: most recently modified jsonl in the last 5 minutes
    candidates = sorted(home.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates and time.time() - candidates[0].stat().st_mtime < 300:
        return candidates[0]
    return None


def is_real_user_prompt(event: dict) -> bool:
    """A real user-typed prompt vs. a tool_result or task-notification."""
    if event.get("type") != "user":
        return False
    msg = event.get("message") or {}
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if isinstance(content, str):
        return "<task-notification>" not in content
    if isinstance(content, list):
        # Must contain at least one plain text block (no tool_result entries)
        has_text = any(isinstance(c, dict) and c.get("type") == "text" for c in content)
        has_tool_result = any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content)
        if has_tool_result:
            return False
        if has_text:
            # Check the text isn't a task-notification
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    if "<task-notification>" in (c.get("text") or ""):
                        return False
            return True
    return False


def collect_user_prompt_timestamps(transcript: Path, limit: int = 20) -> list[datetime]:
    """Walk transcript, return list of UTC datetimes for real user prompts (oldest first)."""
    timestamps = []
    try:
        with open(transcript, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if not is_real_user_prompt(e):
                    continue
                ts = e.get("timestamp")
                if not ts:
                    continue
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    continue
                timestamps.append(dt)
    except FileNotFoundError:
        return []
    return timestamps[-limit:]


def humanize_gap(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h{m:02d}m" if m else f"{h}h"


def tod_bucket(local_dt: datetime) -> str:
    h = local_dt.hour
    if 0 <= h < 5:
        return "late-night"
    if 5 <= h < 9:
        return "early-morning"
    if 9 <= h < 12:
        return "morning"
    if 12 <= h < 14:
        return "midday"
    if 14 <= h < 18:
        return "afternoon"
    if 18 <= h < 22:
        return "evening"
    return "night"


def classify_cadence(gaps_seconds: list[float]) -> str:
    """gaps_seconds: most-recent first."""
    if not gaps_seconds:
        return "session-start"
    last = gaps_seconds[0]
    if last >= 6 * 3600:
        return "resumed-after-long-gap"
    if last >= 2 * 3600:
        return "resumed-after-break"
    if last < 30:
        return "very-rapid-fire"
    if last < 90 and len(gaps_seconds) >= 3 and sum(gaps_seconds[:3]) / 3 < 120:
        return "rapid-fire"
    if last < 300:
        return "active-collaboration"
    if last < 1800:
        return "reflective-pace"
    return "spaced-work"


def classify_phase(gaps_seconds: list[float], cross_day: bool) -> str:
    if not gaps_seconds:
        return "session-start"
    last = gaps_seconds[0]
    if cross_day and last >= 4 * 3600:
        return "resumed-after-overnight"
    if last >= 6 * 3600:
        return "interruption-pivot"
    if last >= 60 * 60:
        return "resumed-after-pause"
    return "continuing"


def main() -> int:
    payload = parse_payload(sys.stdin.read())
    if is_task_notification(payload):
        return 0

    transcript = find_transcript()
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone()
    tod = tod_bucket(now_local)
    now_str = now_local.strftime("%H:%M_%Z")

    if not transcript:
        print(f"[temporal-state] now={now_str}({tod}) | phase=session-start | transcript=unavailable")
        return 0

    prompts = collect_user_prompt_timestamps(transcript)
    if not prompts:
        # First prompt of fresh session
        print(f"[temporal-state] now={now_str}({tod}) | phase=session-start")
        return 0

    # Gaps between consecutive prompts (most-recent first)
    gaps = []
    prev = now_utc
    for ts in reversed(prompts):
        gaps.append((prev - ts).total_seconds())
        prev = ts

    last_gap = gaps[0]
    last_prompt_local = prompts[-1].astimezone()
    cross_day = last_prompt_local.date() != now_local.date()

    cadence = classify_cadence(gaps)
    phase = classify_phase(gaps, cross_day)

    parts = [
        f"gap={humanize_gap(last_gap)}",
        f"cross-day={'yes' if cross_day else 'no'}",
        f"now={now_str}({tod})",
        f"cadence={cadence}",
        f"phase={phase}",
    ]
    print(f"[temporal-state] " + " | ".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
