#!/usr/bin/env python3
"""Codex UserPromptSubmit bridge for Kairos.

Codex CLI and Claude Code use different hook payload shapes, and Codex writes
no transcripts under ~/.claude/projects. This adapter:

  1. extracts the current user prompt and thread id from Codex's hook payload,
  2. synthesizes the Claude-style JSON the Kairos hooks expect,
  3. selects the thread-ring history backend (KAIROS_HISTORY_BACKEND=ring),
  4. runs the ambient injector hooks in order, forwarding their output,
  5. records the prompt timestamp in the thread ring EXACTLY ONCE, after the
     chain (hooks are read-only; every hook in one prompt's chain must see the
     same prior state).

Install: copy next to your Codex config (e.g. ~/.codex/hooks/) and register in
~/.codex/hooks.json; see README.md in this directory.

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
        or os.environ.get("CODEX_THREAD_ID")
        or "codex"
    )


def apply_env_defaults() -> None:
    home = Path.home()
    os.environ.setdefault("KAIROS_HISTORY_BACKEND", "ring")
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

    apply_env_defaults()

    hooks_dir = Path(os.environ.get("KAIROS_HOOKS_DIR", str(Path.home() / ".claude" / "hooks")))
    session_id = resolve_session_id(payload)
    bridged = json.dumps({"session_id": session_id, "prompt": prompt})

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
            print(out)

    try:
        sys.path.insert(0, str(hooks_dir))
        from temporal_lib import ring_record

        ring_record(session_id)
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
