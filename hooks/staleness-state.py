#!/usr/bin/env python3
"""
UserPromptSubmit hook: Layer 3 (self-staleness) delivered as INJECTION.

R7 routing suggested the model call temporal_staleness_audit when the
prompt mentioned a time-volatile tech topic. Measured adherence: 0%
fired-first, 7.7% fired-at-all, the same prescriptive-advisory failure
R8 measured before it. The fix is the one that already worked for Layer 5
(future-state.py): deliver the signal as an ambient orienting line the
model reads without having to act, instead of routing it to a tool.

The gate is keyword AND risk. The line renders only when (a) the prompt
mentions a time-volatile topic (the R7 trigger set, word-boundary matched)
and (b) the audit grades that topic medium or high risk for the current
distance past training cutoff. Low-risk matches stay silent, so fresh
domains cost nothing. Keyword false positives are harmless here: the line
orients, it does not command.

  [staleness] 'api' risk=medium (159d since cutoff, 90d half-life): qualify

Reuses the temporal-staleness MCP module (single source of truth);
hooks/../mcp/temporal-staleness.py resolves in both the repo and the
installed ~/.claude/ layout. Never raises into the prompt path.

Disable with KAIROS_STALENESS_INJECT=0.

Usage in settings.json:
  "UserPromptSubmit": [{
    "hooks": [{ "type": "command", "command": "~/.claude/hooks/staleness-state.py", "timeout": 2000 }]
  }]
"""

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from keywords import R7_TRIGGER_KEYWORDS

TRIGGER_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in R7_TRIGGER_KEYWORDS) + r")\b"
)

# Context window around the matched keyword handed to domain inference; the
# bare keyword alone ("api") under-determines the domain.
CONTEXT_CHARS = 60


def load_staleness_module():
    path = Path(__file__).resolve().parent.parent / "mcp" / "temporal-staleness.py"
    if not path.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("temporal_staleness", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def render(keyword: str, verdict: dict) -> str | None:
    """One orienting line for medium/high risk, None (silence) for low."""
    if verdict.get("risk") not in ("medium", "high"):
        return None
    days = verdict.get("days_since_cutoff")
    half_life = verdict.get("half_life_days")
    suggestion = verdict.get("suggestion") or "qualify"
    return (
        f"[staleness] '{keyword}' risk={verdict['risk']} "
        f"({days}d since cutoff, {half_life}d half-life): {suggestion}"
    )


def main() -> int:
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    if os.environ.get("KAIROS_STALENESS_INJECT", "1") != "1":
        return 0
    try:
        payload = json.loads(raw)
    except Exception:
        payload = {}
    prompt = payload.get("prompt") or ""
    if "<task-notification>" in prompt:
        return 0

    try:
        m = TRIGGER_RE.search(prompt.lower())
        if not m:
            return 0
        mod = load_staleness_module()
        if mod is None:
            return 0
        start, end = m.span()
        context = prompt.lower()[max(0, start - CONTEXT_CHARS):end + CONTEXT_CHARS]
        verdict = mod.assess(context, None)
        line = render(m.group(0), verdict)
        if line:
            print(line)
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
