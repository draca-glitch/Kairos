"""
Shared temporal-state primitives for claude-kit hooks.

Used by:
  - temporal-state.py  (emits [temporal-state] summary line)
  - temporal-routing.py (emits [temporal-routing] advisories based on same state)
  - future Layer 3/4/5 hooks

Single source of truth for: transcript discovery, real-user-prompt filter,
gap/cadence/phase classification, time-of-day bucketing. Pure stdlib.
"""

import json
import os
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
    home = Path.home() / ".claude" / "projects"
    if not home.exists():
        return None

    session_id = os.environ.get("CLAUDE_SESSION_ID", "").strip()
    if session_id:
        for jsonl in home.rglob(f"{session_id}.jsonl"):
            return jsonl

    candidates = sorted(home.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates and time.time() - candidates[0].stat().st_mtime < 300:
        return candidates[0]
    return None


def is_real_user_prompt(event: dict) -> bool:
    if event.get("type") != "user":
        return False
    msg = event.get("message") or {}
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if isinstance(content, str):
        return "<task-notification>" not in content
    if isinstance(content, list):
        has_text = any(isinstance(c, dict) and c.get("type") == "text" for c in content)
        has_tool_result = any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content)
        if has_tool_result:
            return False
        if has_text:
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    if "<task-notification>" in (c.get("text") or ""):
                        return False
            return True
    return False


def collect_user_prompt_timestamps(transcript: Path, limit: int = 20) -> list[datetime]:
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
    timestamps.sort()
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


def compute_state(payload: dict | None = None) -> dict:
    """Return canonical state dict consumed by all temporal hooks.

    Keys: transcript_available, prompts_count, now_utc, now_local, now_str,
    tod, gap_seconds, gap_str, cross_day, cadence, phase, gaps_seconds,
    prompt_text.
    """
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone()
    state = {
        "transcript_available": False,
        "prompts_count": 0,
        "now_utc": now_utc,
        "now_local": now_local,
        "now_str": now_local.strftime("%H:%M_%Z"),
        "tod": tod_bucket(now_local),
        "gap_seconds": None,
        "gap_str": None,
        "cross_day": False,
        "cadence": "session-start",
        "phase": "session-start",
        "gaps_seconds": [],
        "prompt_text": (payload or {}).get("prompt") or "",
    }

    transcript = find_transcript()
    if not transcript:
        return state
    state["transcript_available"] = True

    prompts = collect_user_prompt_timestamps(transcript)
    state["prompts_count"] = len(prompts)
    if not prompts:
        return state

    gaps = []
    prev = now_utc
    for ts in reversed(prompts):
        gaps.append((prev - ts).total_seconds())
        prev = ts

    last_gap = gaps[0]
    last_prompt_local = prompts[-1].astimezone()
    cross_day = last_prompt_local.date() != now_local.date()

    state["gap_seconds"] = last_gap
    state["gap_str"] = humanize_gap(last_gap)
    state["cross_day"] = cross_day
    state["cadence"] = classify_cadence(gaps)
    state["phase"] = classify_phase(gaps, cross_day)
    state["gaps_seconds"] = gaps
    return state
