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

When CLAUDE_TRAINING_CUTOFF is not set the audit runs on an assumed default
cutoff, and the line says "since assumed cutoff" so the day count is not
read as a fact about the model.

Reuses the temporal-staleness MCP module (single source of truth);
hooks/../mcp/temporal-staleness.py resolves in both the repo and the
installed ~/.claude/ layout. Never raises into the prompt path.

Disable with KAIROS_STALENESS_INJECT=0 or `"staleness_inject": false` in
~/.config/kairos/config.json. Env wins over the file.

Usage in settings.json:
  "UserPromptSubmit": [{
    "hooks": [{ "type": "command", "command": "~/.claude/hooks/staleness-state.py", "timeout": 2 }]
  }]
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from keywords import R7_TRIGGER_KEYWORDS
from temporal_lib import setting_bool


def inject_enabled() -> bool:
    return setting_bool("staleness_inject", True)

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
    cutoff = "assumed cutoff" if verdict.get("cutoff_source") == "assumed-default" else "cutoff"
    return (
        f"[staleness] '{keyword}' risk={verdict['risk']} "
        f"({days}d since {cutoff}, {half_life}d half-life): {suggestion}"
    )


def context_window(text: str, start: int, end: int, width: int = CONTEXT_CHARS) -> str:
    """The text around a match, cut at spaces. Domain inference matches whole
    words, so a slice that begins mid-word ("law" out of "flaw") would invent
    a keyword that is not in the prompt."""
    lo, hi = max(0, start - width), min(len(text), end + width)
    if lo > 0:
        cut = text.find(" ", lo, start)
        lo = cut + 1 if cut != -1 else start
    if hi < len(text):
        cut = text.rfind(" ", end, hi)
        hi = cut if cut != -1 else end
    return text[lo:hi]


def main() -> int:
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    if not inject_enabled():
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
        context = context_window(prompt.lower(), start, end)
        verdict = mod.assess(context, None)
        line = render(m.group(0), verdict)
        if line:
            print(line)
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
