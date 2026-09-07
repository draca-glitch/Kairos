#!/usr/bin/env python3
"""
UserPromptSubmit hook: Layer 5 (future-orientation) delivered as INJECTION.

Layer 5's value is "what should the agent anticipate?": overdue tasks,
items due today, expiring memories. The temporal-future MCP exposes this
as a tool, and R8 routing suggested the model call it. Measured adherence
to that prescriptive nudge was ~0%: a "call this tool first" advisory does
not drive behavior, even when the tool has real data behind it.

So this hook delivers the same signal the way Layer 1 delivers time, as an
ambient orienting line the model reads without having to act:

  [obligations] 2 overdue (1 high) · 1 due today · next: 'X' today (brf) · 2 memories expiring

The gate is STATE, not keywords. It speaks only when something is actually
overdue or due today (the case worth surfacing unprompted), which makes it
immune to the keyword-false-positive disease that sank R8 ("I'll do it
tomorrow" does not manufacture an obligation). Forward-time keywords in the
prompt merely WIDEN the gate to also include upcoming-within-horizon tasks
and memories about to expire, so "what's left this week" surfaces the week.

Reuses the temporal-future MCP's query logic (single source of truth);
hooks/../mcp/temporal-future.py resolves correctly in both the repo and the
installed ~/.claude/ layout. Never raises into the prompt path.

Disable with KAIROS_FUTURE_INJECT=0 or `"future_inject": false` in
~/.config/kairos/config.json; horizon via KAIROS_FUTURE_HORIZON_DAYS or
`"future_horizon_days"`. Env wins over the file.

Usage in settings.json:
  "UserPromptSubmit": [{
    "hooks": [{ "type": "command", "command": "~/.claude/hooks/future-state.py", "timeout": 3000 }]
  }]
"""

import importlib.util
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from temporal_lib import setting, setting_bool

# Forward-time triggers (en + sv), mirrors R8's intent. These only WIDEN the
# gate to include upcoming items; they never fabricate an injection on their
# own, so over-matching here is harmless (unlike a prescriptive advisory).
FORWARD_KEYWORDS = re.compile(
    r"\b(deadline|due|overdue|upcoming|schedule[d]?|tomorrow|today|this week|next week|"
    r"soon|what's left|planning|snart|imorgon|imorra|nästa vecka|i veckan|planera|förfaller)\b",
    re.IGNORECASE,
)



def inject_enabled() -> bool:
    return setting_bool("future_inject", True)


def horizon_days() -> int:
    try:
        return int(setting("future_horizon_days", "7"))
    except ValueError:
        return 7


def load_future_module():
    """Load the temporal-future MCP module by path (hyphenated filename)."""
    path = Path(__file__).resolve().parent.parent / "mcp" / "temporal-future.py"
    if not path.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("temporal_future", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def render(result: dict, widened: bool) -> str | None:
    """Build the [obligations] line, or None to stay silent.

    Always-on gate: overdue or due-today. Widened gate (forward keywords
    present): also upcoming-within-horizon tasks and expiring memories.
    """
    tasks = result.get("tasks", {})
    if not tasks.get("available"):
        return None
    counts = tasks.get("counts", {})
    overdue = counts.get("overdue", 0)
    due_today = counts.get("due_today", 0)
    upcoming = counts.get("upcoming_in_horizon", 0)
    mems = result.get("expiring_memories", {})
    expiring = mems.get("count", 0) if mems.get("available") else 0

    # Always-on gate: overdue or due today. Widened gate (the prompt looks
    # ahead): also upcoming tasks and memories about to expire; a memory
    # with days left is forward-looking state in exactly the same sense.
    if not (overdue or due_today or (widened and (upcoming or expiring))):
        return None

    parts = []
    if overdue:
        high = sum(1 for t in tasks.get("overdue", []) if t.get("priority") == "high")
        parts.append(f"{overdue} overdue" + (f" ({high} high)" if high else ""))
    if due_today:
        parts.append(f"{due_today} due today")

    # "next" means the most actionable obligation, not the oldest debt:
    # due-today, else the nearest upcoming (whenever the horizon has one,
    # widened or not; widening only controls whether upcoming-only state
    # produces a line at all), else the most RECENTLY missed overdue task.
    # The previous picker fell back to the MOST overdue, which headlines a
    # long-dead task forever and buries the obligation actually nearest.
    nxt, when = None, None
    if tasks.get("due_today"):
        nxt, when = tasks["due_today"][0], "today"
    elif tasks.get("upcoming"):
        nxt = tasks["upcoming"][0]
        when = f"in {nxt.get('days_until')}d"
    elif tasks.get("overdue"):
        nxt = tasks["overdue"][-1]  # least stale (ORDER BY due_date ASC)
        when = f"{abs(nxt.get('days_until') or 0)}d overdue"
    if nxt:
        title = (nxt.get("title") or "")[:50]
        area = nxt.get("area") or ""
        parts.append(f"next: '{title}' {when}" + (f" ({area})" if area else ""))

    if expiring:
        parts.append(f"{expiring} memory(ies) expiring")

    return "[obligations] " + " · ".join(parts) if parts else None


def main() -> int:
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    if "<task-notification>" in raw:
        return 0
    if not inject_enabled():
        return 0

    try:
        mod = load_future_module()
        if mod is None:
            return 0
        widened = bool(FORWARD_KEYWORDS.search(raw))
        result = mod.tool_temporal_future_query({"horizon_days": horizon_days()})
        line = render(result, widened)
        if line:
            print(line)
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
