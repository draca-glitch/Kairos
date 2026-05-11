#!/usr/bin/env python3
"""
Layer 6 falsifiability tracker: PostToolUse hook that records every tool
call alongside the temporal-routing advisory in force at the time, so
adherence statistics can be computed offline.

Reads /root/work/temporal-routing-state.json (written by
temporal-routing.py at UserPromptSubmit time) to know the current
advisory. Appends one JSONL record per tool call to
/root/work/temporal-routing-log.jsonl.

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

Failure modes are silent — the tracker must never block tool execution.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


STATE_FILE = Path("/root/work/temporal-routing-state.json")
LOG_FILE = Path("/root/work/temporal-routing-log.jsonl")


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
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
