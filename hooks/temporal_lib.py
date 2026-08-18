"""
Shared temporal-state primitives for kairos hooks.

Used by:
  - temporal-state.py  (emits [temporal-state] summary line)
  - temporal-routing.py (emits [temporal-routing] advisories based on same state)
  - future Layer 3/4/5 hooks

Single source of truth for: transcript discovery, real-user-prompt filter,
gap/cadence/phase classification, time-of-day bucketing. Pure stdlib.
"""

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path


# Idle cutoff for transcript-mtime fallback when CLAUDE_SESSION_ID is absent.
# Defaults to 4h so the temporal pipeline survives ordinary work pauses
# (lunch, meetings) without degrading silently to "session-start". Override
# via env when running headless/long-idle sessions.
TRANSCRIPT_MAX_IDLE_SECONDS = int(
    os.environ.get("CLAUDE_KIT_TRANSCRIPT_MAX_IDLE_SECONDS", "14400")
)

# Fixed English tuple; strftime %a is locale-dependent and the injected line
# must be stable for downstream parsing regardless of server locale.
DOW = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


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
    if candidates and time.time() - candidates[0].stat().st_mtime < TRANSCRIPT_MAX_IDLE_SECONDS:
        return candidates[0]
    return None


# --- Thread-ring history backend -------------------------------------------
#
# Claude Code writes transcripts under ~/.claude/projects, so the transcript
# backend above can read prompt history for free. Other harnesses (Codex CLI
# via adapters/codex/) have no such transcripts; for them, prompt timestamps
# are kept in a small per-thread ring under the kit state dir. Hooks only READ
# the ring (all hooks in one prompt's chain must see identical prior state);
# the harness adapter calls ring_record() exactly once per prompt, after the
# hook chain has run.
#
# Select with KAIROS_HISTORY_BACKEND=ring (default: transcript, unchanged).
# Thread identity comes from payload["session_id"] or KAIROS_THREAD_ID.

RING_LIMIT = 20
RING_DIR_NAME = "thread-rings"
RING_STALE_SECONDS = int(os.environ.get("KAIROS_RING_STALE_SECONDS", str(30 * 86400)))


def history_backend() -> str:
    return os.environ.get("KAIROS_HISTORY_BACKEND", "transcript").strip().lower()


def state_dir() -> Path:
    return Path(os.environ.get("CLAUDE_KIT_STATE_DIR", str(Path.home() / ".claude" / "state")))


def resolve_thread_id(payload: dict | None) -> str:
    for value in ((payload or {}).get("session_id"), os.environ.get("KAIROS_THREAD_ID")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _ring_path(thread_id: str) -> Path:
    # Hash the thread id: external harnesses control its content, so it never
    # touches the filesystem as a raw name.
    digest = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:16]
    return state_dir() / RING_DIR_NAME / f"{digest}.json"


def ring_load(thread_id: str, limit: int = RING_LIMIT) -> list[datetime]:
    """Prior prompt timestamps for a thread, oldest first. Corrupt or missing
    state degrades to an empty list (session-start)."""
    if not thread_id:
        return []
    try:
        data = json.loads(_ring_path(thread_id).read_text(encoding="utf-8"))
        raw = data.get("timestamps")
    except Exception:
        return []
    timestamps = []
    for item in raw if isinstance(raw, list) else []:
        try:
            dt = datetime.fromisoformat(str(item))
        except Exception:
            continue
        if dt.tzinfo is not None:
            timestamps.append(dt)
    timestamps.sort()
    return timestamps[-limit:]


def ring_record(thread_id: str, when: datetime | None = None) -> None:
    """Append one prompt timestamp to the thread ring, atomically. Call ONCE
    per prompt, after the hook chain has read the previous state."""
    if not thread_id:
        return
    when = when or datetime.now(timezone.utc)
    path = _ring_path(thread_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamps = ring_load(thread_id)
        timestamps.append(when)
        timestamps = timestamps[-RING_LIMIT:]
        tmp = path.parent / f"{path.name}.{os.getpid()}.tmp"
        tmp.write_text(
            json.dumps({"timestamps": [t.isoformat() for t in timestamps]}),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except Exception:
        return
    _prune_stale_rings(path.parent, keep=path)


def _prune_stale_rings(ring_dir: Path, keep: Path | None = None) -> None:
    cutoff = time.time() - RING_STALE_SECONDS
    try:
        for f in ring_dir.glob("*.json"):
            if keep is not None and f == keep:
                continue
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except FileNotFoundError:
                continue
    except Exception:
        return


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
        "now_str": f"{DOW[now_local.weekday()]}_{now_local.strftime('%H:%M_%Z')}",
        "tod": tod_bucket(now_local),
        "gap_seconds": None,
        "gap_str": None,
        "cross_day": False,
        "cadence": "session-start",
        "phase": "session-start",
        "gaps_seconds": [],
        "prompt_text": (payload or {}).get("prompt") or "",
    }

    if history_backend() == "ring":
        # The ring is available by construction; an empty one is session-start.
        state["transcript_available"] = True
        prompts = ring_load(resolve_thread_id(payload))
        state["prompts_count"] = len(prompts)
        if not prompts:
            return state
        return _apply_prompt_history(state, prompts, now_utc, now_local)

    transcript = find_transcript()
    if not transcript:
        return state
    state["transcript_available"] = True

    prompts = collect_user_prompt_timestamps(transcript)
    state["prompts_count"] = len(prompts)
    if not prompts:
        return state
    return _apply_prompt_history(state, prompts, now_utc, now_local)


def _apply_prompt_history(
    state: dict, prompts: list[datetime], now_utc: datetime, now_local: datetime
) -> dict:
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
