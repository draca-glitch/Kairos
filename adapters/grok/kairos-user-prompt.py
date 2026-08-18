#!/usr/bin/env python3
"""Grok CLI UserPromptSubmit bridge for Kairos.

Grok writes no transcripts under ~/.claude/projects and its hook payload uses
camelCase keys (sessionId), so raw Kairos hooks classify every prompt as
phase=session-start (or, within the transcript-idle window, steal a concurrent
Claude session's thread). This adapter:

  1. extracts the current user prompt and thread id (sessionId/session_id)
     from Grok's hook payload,
  2. synthesizes the snake_case Claude-style payload the Kairos hooks expect,
  3. selects the thread-ring history backend (KAIROS_HISTORY_BACKEND=ring)
     and exports KAIROS_THREAD_ID for the chain (time.sh marker isolation),
  4. runs the ambient injector hooks in order and collects their output,
  5. emits the collected lines as UserPromptSubmit hookSpecificOutput
     additionalContext JSON (the Claude hook contract Grok's compatibility
     layer is expected to honor; plain stdout is observe-only in Grok),
  6. records the prompt timestamp in the thread ring EXACTLY ONCE, after the
     chain (hooks are read-only; every hook in one prompt's chain must see
     the same prior state).

Install: copy into Grok's hook directory and register for UserPromptSubmit;
see README.md in this directory.

Env knobs (all optional):
  KAIROS_HOOKS_DIR       hook scripts location (default ~/.claude/hooks)
  CLAUDE_KIT_STATE_DIR   kit state dir (default ~/.claude/state)
  KAIROS_MEMORY_DB       Mnemos db for future-state (default: ~/.mnemos/memory.db
                         if present, else ~/work/memory.db)
  KAIROS_TASKS_DB        tasks db for future-state (default ~/work/tasks.db)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HOOK_ORDER = [
    "time.sh",
    "temporal-state.py",
    "temporal-routing.py",
    "future-state.py",
    "staleness-state.py",
]

HOOK_TIMEOUT_SECONDS = 2.0


def _text_from_content(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("input_text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def extract_prompt(payload: dict, raw: str) -> str:
    for key in ("prompt", "user_prompt", "userPrompt", "input", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value

    for key in ("message", "user_message", "userMessage"):
        value = payload.get(key)
        if isinstance(value, dict):
            text = _text_from_content(value.get("content"))
            if text:
                return text
        elif isinstance(value, str) and value:
            return value

    messages = payload.get("messages")
    if isinstance(messages, list):
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                text = _text_from_content(msg.get("content"))
                if text:
                    return text

    return raw if raw and not raw.lstrip().startswith("{") else ""


def resolve_session_id(payload: dict) -> str:
    return (
        payload.get("session_id")
        or payload.get("sessionId")
        or payload.get("thread_id")
        or payload.get("conversation_id")
        or os.environ.get("GROK_SESSION_ID")
        or "grok"
    )


def apply_env_defaults(session_id: str) -> None:
    home = Path.home()
    os.environ.setdefault("KAIROS_HISTORY_BACKEND", "ring")
    os.environ.setdefault("KAIROS_THREAD_ID", session_id)
    os.environ.setdefault("CLAUDE_KIT_STATE_DIR", str(home / ".claude" / "state"))
    mnemos_db = home / ".mnemos" / "memory.db"
    os.environ.setdefault(
        "KAIROS_MEMORY_DB",
        str(mnemos_db if mnemos_db.exists() else home / "work" / "memory.db"),
    )
    os.environ.setdefault("KAIROS_TASKS_DB", str(home / "work" / "tasks.db"))


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    prompt = extract_prompt(payload, raw)
    if "<task-notification>" in prompt:
        return 0

    session_id = resolve_session_id(payload)
    apply_env_defaults(session_id)

    hooks_dir = Path(os.environ.get("KAIROS_HOOKS_DIR", str(Path.home() / ".claude" / "hooks")))
    bridged = json.dumps({"session_id": session_id, "prompt": prompt})

    lines = []
    for name in HOOK_ORDER:
        path = hooks_dir / name
        if not path.exists():
            continue
        try:
            proc = subprocess.run(
                [str(path)],
                input=bridged,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=HOOK_TIMEOUT_SECONDS,
                check=False,
            )
        except Exception:
            continue
        out = proc.stdout.strip()
        if out:
            lines.append(out)

    if lines:
        # Grok treats plain UserPromptSubmit stdout as observe-only, so the
        # injector lines ride the Claude hook JSON contract instead. If Grok
        # does not deliver additionalContext either, that is a Grok product
        # gap; see README.
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "\n".join(lines),
            },
        }))

    try:
        sys.path.insert(0, str(hooks_dir))
        from temporal_lib import ring_record

        ring_record(session_id)
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
