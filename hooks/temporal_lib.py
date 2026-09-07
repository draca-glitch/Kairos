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


# --- Shared configuration ----------------------------------------------------
#
# Precedence for every knob: KAIROS_<NAME> env, then the config file, then the
# built-in default. The file is ~/.config/kairos/config.json (override the
# path with KAIROS_CONFIG). Local preferences belong in the file: hooks are
# COPIES under ~/.claude/hooks and a reinstall or fleet converge re-copies
# them, so a preference edited into a hook does not survive; a preference in
# the file does, and every harness adapter reads the same file.

_CONFIG_CACHE: dict | None = None


def config_path() -> Path:
    override = os.environ.get("KAIROS_CONFIG", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "kairos" / "config.json"


def reset_config_cache() -> None:
    global _CONFIG_CACHE
    _CONFIG_CACHE = None


def load_config() -> dict:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        try:
            data = json.loads(config_path().read_text(encoding="utf-8"))
            _CONFIG_CACHE = data if isinstance(data, dict) else {}
        except Exception:
            _CONFIG_CACHE = {}
    return _CONFIG_CACHE


def setting(name: str, default: str | None = None) -> str | None:
    """Resolve one knob as a string: env KAIROS_<NAME>, else config key
    <name>, else default. Booleans in the file come back as "1"/"0" so
    callers can treat env and file values identically."""
    env = os.environ.get(f"KAIROS_{name.upper()}")
    if env is not None and env.strip() != "":
        return env.strip()
    value = load_config().get(name.lower())
    if value is None:
        return default
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def setting_bool(name: str, default: bool) -> bool:
    raw = setting(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def memory_db_path() -> Path:
    """The Mnemos store Layer 5 reads. Explicit configuration first, then
    Mnemos's own MNEMOS_DB, then the first existing of the two conventional
    locations, work store before the ~/.mnemos default: on a host where the
    live store is under ~/work, ~/.mnemos/memory.db tends to be an empty
    leftover from a first run, and preferring it reads nothing, silently."""
    explicit = setting("memory_db") or os.environ.get("MNEMOS_DB", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    home = Path.home()
    for candidate in (home / "work" / "memory.db", home / ".mnemos" / "memory.db"):
        if candidate.exists():
            return candidate
    return home / "work" / "memory.db"


def tasks_db_path() -> Path:
    explicit = setting("tasks_db")
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / "work" / "tasks.db"


def parse_payload(raw: str) -> dict:
    try:
        return json.loads(raw)
    except Exception:
        return {}


def is_task_notification(payload: dict) -> bool:
    prompt = payload.get("prompt") or ""
    return "<task-notification>" in prompt


def find_transcript(payload: dict | None = None) -> Path | None:
    home = Path.home() / ".claude" / "projects"
    if not home.exists():
        return None

    session_id = (
        os.environ.get("CLAUDE_SESSION_ID", "").strip()
        or str((payload or {}).get("session_id") or "").strip()
    )
    if session_id:
        for jsonl in home.rglob(f"{session_id}.jsonl"):
            return jsonl

    # Newest-transcript mtime fallback, but ONLY when a Claude session
    # identity was present (env or payload) and its file was simply not
    # found (e.g. rotation). Without any session identity we are most
    # likely a foreign harness (Grok, Codex without adapter) whose raw
    # hooks would otherwise steal a concurrent Claude session's thread
    # and report its cadence as our own; session-start is the honest
    # answer there.
    if not session_id:
        return None

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


def ring_stale_seconds() -> int:
    try:
        return int(setting("ring_stale_seconds", str(30 * 86400)))
    except ValueError:
        return 30 * 86400


def history_backend() -> str:
    return (setting("history_backend", "transcript") or "transcript").strip().lower()


def state_dir() -> Path:
    legacy = os.environ.get("CLAUDE_KIT_STATE_DIR", "").strip()
    if legacy:
        return Path(legacy).expanduser()
    return Path(setting("state_dir", str(Path.home() / ".claude" / "state"))).expanduser()


def resolve_thread_id(payload: dict | None) -> str:
    # Payload first (session_id, then Grok's camelCase sessionId), then env:
    # the explicit kit var, then per-harness session vars.
    candidates = [
        (payload or {}).get("session_id"),
        (payload or {}).get("sessionId"),
        os.environ.get("KAIROS_THREAD_ID"),
        os.environ.get("GROK_SESSION_ID"),
        os.environ.get("CODEX_THREAD_ID"),
        os.environ.get("CLAUDE_SESSION_ID"),
    ]
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _ring_path(thread_id: str) -> Path:
    # Hash the thread id: external harnesses control its content, so it never
    # touches the filesystem as a raw name.
    digest = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:16]
    return state_dir() / RING_DIR_NAME / f"{digest}.json"


def _ring_read(thread_id: str) -> dict:
    try:
        data = json.loads(_ring_path(thread_id).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_stamps(raw, limit: int) -> list[datetime]:
    stamps = []
    for item in raw if isinstance(raw, list) else []:
        try:
            dt = datetime.fromisoformat(str(item))
        except Exception:
            continue
        if dt.tzinfo is not None:
            stamps.append(dt)
    stamps.sort()
    return stamps[-limit:]


def ring_load(thread_id: str, limit: int = RING_LIMIT) -> list[datetime]:
    """Prior prompt timestamps for a thread, oldest first. Corrupt or missing
    state degrades to an empty list (session-start)."""
    if not thread_id:
        return []
    return _parse_stamps(_ring_read(thread_id).get("timestamps"), limit)


def ring_load_replies(thread_id: str, limit: int = RING_LIMIT) -> list[datetime]:
    """Assistant turn-end timestamps for a thread, oldest first. Empty unless
    the harness runs hooks/turn-end.py, in which case cadence can classify on
    the user's own gap instead of prompt-to-prompt."""
    if not thread_id:
        return []
    return _parse_stamps(_ring_read(thread_id).get("replies"), limit)


def _ring_append(thread_id: str, key: str, when: datetime | None) -> None:
    if not thread_id:
        return
    when = when or datetime.now(timezone.utc)
    path = _ring_path(thread_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = _ring_read(thread_id)
        stamps = _parse_stamps(data.get(key), RING_LIMIT)
        stamps.append(when)
        data[key] = [t.isoformat() for t in stamps[-RING_LIMIT:]]
        tmp = path.parent / f"{path.name}.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        return
    _prune_stale_rings(path.parent, keep=path)


def ring_record(thread_id: str, when: datetime | None = None) -> None:
    """Append one prompt timestamp to the thread ring, atomically. Call ONCE
    per prompt, after the hook chain has read the previous state."""
    _ring_append(thread_id, "timestamps", when)


def ring_record_reply(thread_id: str, when: datetime | None = None) -> None:
    """Append one assistant turn-end timestamp. Called by hooks/turn-end.py."""
    _ring_append(thread_id, "replies", when)


def _prune_stale_rings(ring_dir: Path, keep: Path | None = None) -> None:
    cutoff = time.time() - ring_stale_seconds()
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


def _event_time(event: dict) -> datetime | None:
    ts = event.get("timestamp")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def collect_turn_timestamps(transcript: Path, limit: int = 20) -> tuple[list[datetime], list[datetime]]:
    """(prompts, replies): real user prompts and every assistant event, each
    oldest first. Claude Code stamps every assistant record, so the last
    assistant event before a prompt is when the previous turn ended, which is
    what the user's own gap is measured from. Replies are trimmed to those
    since the oldest kept prompt."""
    prompts, replies = [], []
    try:
        with open(transcript, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if is_real_user_prompt(e):
                    dt = _event_time(e)
                    if dt is not None:
                        prompts.append(dt)
                elif e.get("type") == "assistant":
                    dt = _event_time(e)
                    if dt is not None:
                        replies.append(dt)
    except FileNotFoundError:
        return [], []
    prompts.sort()
    prompts = prompts[-limit:]
    replies.sort()
    if prompts:
        replies = [r for r in replies if r >= prompts[0]]
    return prompts, replies


def collect_user_prompt_timestamps(transcript: Path, limit: int = 20) -> list[datetime]:
    return collect_turn_timestamps(transcript, limit)[0]


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


def user_gaps(prompts: list[datetime], replies: list[datetime], now: datetime
              ) -> tuple[list[float], str | None, float | None]:
    """Gaps for classification, newest first, measured from the user's side.

    Entry 0 is the gap before the prompt being submitted now; entry i is the
    gap before prompt -i. Each gap runs from the assistant's last reply in
    that interval when one exists, else from the previous prompt. The basis
    ("reply" or "turn") describes entry 0 only: it is the honest label for
    whether the current cadence reading is the user's own pause or includes
    the assistant's working time. The third value is the raw prompt-to-prompt
    gap for display. Empty history returns ([], None, None)."""
    if not prompts:
        return [], None, None
    replies = sorted(replies)
    turn_gap = (now - prompts[-1]).total_seconds()
    last_reply = replies[-1] if replies else None
    if last_reply is not None and last_reply > prompts[-1]:
        gaps = [(now - last_reply).total_seconds()]
        basis = "reply"
    else:
        gaps = [turn_gap]
        basis = "turn"
    for i in range(len(prompts) - 1, 0, -1):
        prev_prompt, this_prompt = prompts[i - 1], prompts[i]
        between = [r for r in replies if prev_prompt < r < this_prompt]
        anchor = max(between) if between else prev_prompt
        gaps.append((this_prompt - anchor).total_seconds())
    return gaps, basis, turn_gap


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
    tod, gap_seconds, gap_str, gap_basis, reply_gap_seconds, reply_gap_str,
    turn_gap_seconds, turn_gap_str, cross_day, cadence, phase, gaps_seconds,
    prompt_text.

    gap_seconds is the user's gap (since the assistant's last reply when that
    timestamp exists, else since the previous prompt) and is what cadence and
    phase classify on; gap_basis says which. turn_gap_seconds is always the
    raw prompt-to-prompt measurement.
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
        "gap_basis": None,
        "reply_gap_seconds": None,
        "reply_gap_str": None,
        "turn_gap_seconds": None,
        "turn_gap_str": None,
        "cross_day": False,
        "cadence": "session-start",
        "phase": "session-start",
        "gaps_seconds": [],
        "prompt_text": (payload or {}).get("prompt") or "",
    }

    if history_backend() == "ring":
        # The ring is available by construction; an empty one is session-start.
        state["transcript_available"] = True
        thread_id = resolve_thread_id(payload)
        prompts = ring_load(thread_id)
        state["prompts_count"] = len(prompts)
        if not prompts:
            return state
        return _apply_prompt_history(state, prompts, ring_load_replies(thread_id), now_utc, now_local)

    transcript = find_transcript(payload)
    if not transcript:
        return state
    state["transcript_available"] = True

    prompts, replies = collect_turn_timestamps(transcript)
    state["prompts_count"] = len(prompts)
    if not prompts:
        return state
    return _apply_prompt_history(state, prompts, replies, now_utc, now_local)


def _apply_prompt_history(
    state: dict, prompts: list[datetime], replies: list[datetime],
    now_utc: datetime, now_local: datetime,
) -> dict:
    gaps, basis, turn_gap = user_gaps(prompts, replies, now_utc)

    last_gap = gaps[0]
    last_prompt_local = prompts[-1].astimezone()
    cross_day = last_prompt_local.date() != now_local.date()

    state["gap_seconds"] = last_gap
    state["gap_str"] = humanize_gap(last_gap)
    state["gap_basis"] = basis
    state["turn_gap_seconds"] = turn_gap
    state["turn_gap_str"] = humanize_gap(turn_gap)
    if basis == "reply":
        state["reply_gap_seconds"] = last_gap
        state["reply_gap_str"] = state["gap_str"]
    state["cross_day"] = cross_day
    state["cadence"] = classify_cadence(gaps)
    state["phase"] = classify_phase(gaps, cross_day)
    state["gaps_seconds"] = gaps
    return state
