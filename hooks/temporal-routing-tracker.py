#!/usr/bin/env python3
"""
Layer 6 falsifiability tracker: PostToolUse hook that records every tool
call alongside the temporal-routing advisory in force at the time, so
adherence statistics can be computed offline.

Reads <STATE_DIR>/temporal-routing-state.json (written by
temporal-routing.py at UserPromptSubmit time) to know the current
advisory. Appends one JSONL record per tool call to
<STATE_DIR>/temporal-routing-log.jsonl. STATE_DIR defaults to
~/.claude/state/, override via CLAUDE_KIT_STATE_DIR.

Record schema:
  {
    "ts":            ISO timestamp,
    "tool":          tool name,
    "advisory_ts":   advisory write time,
    "suggests":      [...],
    "skips":         [...],
    "cadence":       cadence at advisory time,
    "phase":         phase at advisory time,
    "gap_str":       gap at advisory time
  }

Offline analysis can group tool sequences by (advisory_ts, prompt-turn)
and compute: did `memory_search` happen before other tools when
suggest=memory_search-first was in force? Etc.

Failure modes are silent, the tracker must never block tool execution.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


STATE_DIR = Path(os.environ.get("CLAUDE_KIT_STATE_DIR", str(Path.home() / ".claude" / "state")))
STATE_FILE = STATE_DIR / "temporal-routing-state.json"
LOG_FILE = STATE_DIR / "temporal-routing-log.jsonl"
LOG_ROTATE_BYTES = int(os.environ.get("CLAUDE_KIT_LOG_ROTATE_BYTES", str(10 * 1024 * 1024)))
LOG_KEEP_ROTATIONS = int(os.environ.get("CLAUDE_KIT_LOG_KEEP_ROTATIONS", "3"))


def rotate_if_oversized() -> None:
    try:
        if not LOG_FILE.exists() or LOG_FILE.stat().st_size < LOG_ROTATE_BYTES:
            return
        for i in range(LOG_KEEP_ROTATIONS, 0, -1):
            src = LOG_FILE.with_suffix(LOG_FILE.suffix + f".{i}")
            dst = LOG_FILE.with_suffix(LOG_FILE.suffix + f".{i + 1}")
            if src.exists():
                if i == LOG_KEEP_ROTATIONS:
                    src.unlink()
                else:
                    src.rename(dst)
        LOG_FILE.rename(LOG_FILE.with_suffix(LOG_FILE.suffix + ".1"))
    except Exception:
        pass


def read_payload() -> dict:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except Exception:
        return {}


def tool_name_from(payload: dict) -> str:
    # Newer Claude Code passes tool_name in stdin payload; older relies on env.
    return (
        payload.get("tool_name")
        or payload.get("toolName")
        or os.environ.get("CLAUDE_TOOL_NAME")
        or os.environ.get("TOOL_NAME")
        or "unknown"
    )


def session_id_from(payload: dict) -> str:
    return (
        payload.get("session_id")
        or payload.get("sessionId")
        or os.environ.get("CLAUDE_SESSION_ID")
        or ""
    )


def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def main() -> int:
    payload = read_payload()
    tool = tool_name_from(payload)
    state = read_state()

    record = {
        "ts": datetime.now(timezone.utc).astimezone().isoformat(),
        "session_id": session_id_from(payload),
        "tool": tool,
        "advisory_ts": state.get("ts"),
        "suggests": state.get("suggests") or [],
        "skips": state.get("skips") or [],
        "cadence": state.get("cadence"),
        "phase": state.get("phase"),
        "gap_str": state.get("gap_str"),
    }

    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        rotate_if_oversized()
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
