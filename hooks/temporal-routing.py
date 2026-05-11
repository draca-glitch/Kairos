#!/usr/bin/env python3
"""
Layer 6: UserPromptSubmit hook that translates temporal state into
deterministic tool-routing advisories. Sibling to temporal-state.py.

Where temporal-state.py *describes* the temporal context, this hook
*recommends* procedural adjustments (which tool to call first, what to
skip, what posture to take). Output is single-line, low-token, and
silent when no rule fires so Claude isn't nudged when nothing matters.

Output format:
  [temporal-routing] suggest=memory_search-first,read-CLAUDE.md-first | skip=TaskCreate-overhead | reason=gap=18m,phase=session-start

Side effect: writes <STATE_DIR>/temporal-routing-state.json with the
current advisory so the post-tool-use tracker can match tool calls
against the advisory in force when they were made (falsifiability log).
STATE_DIR defaults to ~/.claude/state/, override via CLAUDE_KIT_STATE_DIR.

Rules v0 (deterministic, no LLM):
  R1  gap >= 30m                                       → suggest memory_search-first
  R2  cross-day=yes AND gap >= 4h                      → suggest memory_search-first; flag staleness
  R3  cadence in {rapid-fire, very-rapid-fire}         → skip TaskCreate-overhead, skip preamble
  R4  phase=session-start                              → suggest read-CLAUDE.md-first
  R5  cadence=reflective-pace AND prompt_chars > 200   → suggest write-longer-reasoning-prose
  R6  tod=late-night AND resumed-after-* cadence       → suggest confirm-before-destructive
  R7  prompt mentions time-volatile-tech keywords      → suggest temporal_staleness_audit-first
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from temporal_lib import compute_state, is_task_notification, parse_payload


STATE_DIR = Path(os.environ.get("CLAUDE_KIT_STATE_DIR", str(Path.home() / ".claude" / "state")))
STATE_FILE = STATE_DIR / "temporal-routing-state.json"

# Keywords that trigger Layer 3 (staleness) routing. Kept narrow on purpose:
# topics where 4+ months since training cutoff genuinely matters and where
# the model otherwise tends to answer confidently from stale knowledge.
STALENESS_TRIGGER_KEYWORDS = (
    "api", "library", "framework", "package", "sdk", "cve",
    "vulnerability", "vulnerab", "pricing", "price", "cost",
    "model version", "latest version", "release notes",
    "deprecat", "breaking change", "new in", "as of",
)


def evaluate_rules(state: dict) -> tuple[list[str], list[str], list[str]]:
    """Return (suggests, skips, reasons), empty lists when no rules fire."""
    suggests: list[str] = []
    skips: list[str] = []
    reasons: list[str] = []

    gap = state.get("gap_seconds") or 0
    cadence = state.get("cadence", "")
    phase = state.get("phase", "")
    tod = state.get("tod", "")
    cross_day = state.get("cross_day", False)
    prompt_chars = len(state.get("prompt_text") or "")

    # R1: long gap → check memory first
    if gap >= 1800:
        suggests.append("memory_search-first")
        reasons.append(f"gap={state.get('gap_str')}")

    # R2: cross-day with substantial gap → memory + staleness flag
    if cross_day and gap >= 4 * 3600:
        if "memory_search-first" not in suggests:
            suggests.append("memory_search-first")
        suggests.append("flag-staleness")
        reasons.append("cross-day=yes")

    # R3: rapid-fire → trim overhead
    if cadence in {"rapid-fire", "very-rapid-fire"}:
        skips.append("TaskCreate-overhead")
        skips.append("preamble")
        reasons.append(f"cadence={cadence}")

    # R4: session-start → ground in project context
    if phase == "session-start":
        suggests.append("read-CLAUDE.md-first")
        reasons.append("phase=session-start")

    # R5: reflective + substantial prompt → spend tokens on reasoning prose
    # (extended-thinking is a request-level setting the model can't toggle,
    # so the actionable advice is to write longer reasoning in the response).
    if cadence == "reflective-pace" and prompt_chars > 200:
        suggests.append("write-longer-reasoning-prose")
        reasons.append(f"reflective+chars={prompt_chars}")

    # R6: late-night resumption → confirmation posture
    if tod == "late-night" and cadence in {"resumed-after-break", "resumed-after-long-gap"}:
        suggests.append("confirm-before-destructive")
        reasons.append(f"tod=late-night+{cadence}")

    # R7: prompt mentions time-volatile tech topics → consult Layer 3
    prompt_lower = (state.get("prompt_text") or "").lower()
    if prompt_lower:
        hit = next((kw for kw in STALENESS_TRIGGER_KEYWORDS if kw in prompt_lower), None)
        if hit:
            suggests.append("temporal_staleness_audit-first")
            reasons.append(f"staleness-trigger={hit}")

    return suggests, skips, reasons


def render_line(suggests: list[str], skips: list[str], reasons: list[str]) -> str:
    parts = []
    if suggests:
        parts.append(f"suggest={','.join(suggests)}")
    if skips:
        parts.append(f"skip={','.join(skips)}")
    if reasons:
        parts.append(f"reason={','.join(reasons)}")
    return "[temporal-routing] " + " | ".join(parts)


def write_state_file(state: dict, suggests: list[str], skips: list[str], reasons: list[str]) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({
            "ts": state["now_local"].isoformat(),
            "gap_str": state.get("gap_str"),
            "cadence": state.get("cadence"),
            "phase": state.get("phase"),
            "tod": state.get("tod"),
            "cross_day": state.get("cross_day"),
            "suggests": suggests,
            "skips": skips,
            "reasons": reasons,
        }))
    except Exception:
        pass


def main() -> int:
    payload = parse_payload(sys.stdin.read())
    if is_task_notification(payload):
        return 0

    state = compute_state(payload)
    suggests, skips, reasons = evaluate_rules(state)

    write_state_file(state, suggests, skips, reasons)

    if not suggests and not skips:
        return 0

    print(render_line(suggests, skips, reasons))
    return 0


if __name__ == "__main__":
    sys.exit(main())
