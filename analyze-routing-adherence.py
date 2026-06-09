#!/usr/bin/env python3
"""
Compute adherence statistics over temporal-routing-log.jsonl.

For each prompt-turn (identified by advisory_ts) the temporal-routing
hook emitted some combination of `suggests` and `skips`. The PostToolUse
tracker recorded which tools the model actually called during that turn.

This script joins the two streams and answers, per advisory class:
  - When skip=X was in force, how often did the model still call X?
  - When suggest=Y-first was in force, did Y fire first, fire late
    (somewhere in the turn but not first), or never fire at all?

The three-way suggest split de-conflates "followed but not literally
first" from "never followed", which a single followed/violated bar
wrongly merges into one failure bucket. A turn where the suggested tool
ran second (after, say, a memory_search) is adherence in spirit; scoring
it identically to a turn where the tool never ran makes the raw rate read
worse than reality. The residual not-fired bucket still blends genuine
false-positive advisories (correctly ignored) with genuinely-missed ones;
separating those needs a judgment layer over turn context, not the log.

Output: a table to stdout. Exit 0 always (read-only).

Usage:
  ./analyze-routing-adherence.py
  ./analyze-routing-adherence.py --log /custom/path.jsonl
  ./analyze-routing-adherence.py --since 2026-05-01
  ./analyze-routing-adherence.py --session-id <uuid>
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_LOG = Path(
    os.environ.get("CLAUDE_KIT_STATE_DIR", str(Path.home() / ".claude" / "state"))
) / "temporal-routing-log.jsonl"


SKIP_TO_TOOL_PREFIX = {
    "TaskCreate-overhead": "TaskCreate",
    "preamble": None,  # not a tool, treated as advisory-only
}

SUGGEST_TO_TOOL_PREFIX = {
    "memory_search-first": "mcp__agent-memory__memory_search",
    "read-CLAUDE.md-first": "Read",
    "temporal_staleness_audit-first": "mcp__temporal-staleness__temporal_staleness_audit",
    "temporal_future_query-first": "mcp__temporal-future__temporal_future_query",
    "flag-staleness": None,
    "extended-thinking-ok": None,
    "write-longer-reasoning-prose": None,
    "confirm-before-destructive": None,
}


def load_log(path: Path, since: datetime | None, session_id: str | None) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if since:
                try:
                    ts = datetime.fromisoformat(r.get("ts", "").replace("Z", "+00:00"))
                    if ts < since:
                        continue
                except Exception:
                    pass
            if session_id and (r.get("session_id") or "") != session_id:
                continue
            records.append(r)
    return records


def group_turns(records: list[dict]) -> dict[str, list[dict]]:
    """Group tool calls into prompt-turns keyed by (session_id, advisory_ts).

    advisory_ts alone is ambiguous with concurrent sessions: two sessions can
    interleave tool calls against the same globally-written advisory, and a
    merged group corrupts the 'first tool in turn' computation. Records from
    pre-session-id logs (no session_id field) degrade to the old behavior.
    """
    turns: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        adv = r.get("advisory_ts") or "<no-advisory>"
        key = f"{r.get('session_id') or ''}|{adv}"
        turns[key].append(r)
    for key in turns:
        turns[key].sort(key=lambda r: r.get("ts", ""))
    return turns


def analyze_skips(turns: dict[str, list[dict]]) -> dict[str, dict]:
    stats: dict[str, dict] = defaultdict(lambda: {"turns": 0, "violated": 0, "followed": 0})
    for adv, calls in turns.items():
        if not calls:
            continue
        skips = calls[0].get("skips") or []
        for skip in skips:
            target = SKIP_TO_TOOL_PREFIX.get(skip)
            if target is None:
                continue
            stats[skip]["turns"] += 1
            violated = any((c.get("tool") or "").startswith(target) for c in calls)
            stats[skip]["violated" if violated else "followed"] += 1
    return stats


def analyze_suggests_first(turns: dict[str, list[dict]]) -> dict[str, dict]:
    """Three-way split per suggest advisory.

    followed_first : suggested tool was the first tool call in the turn
    followed_late  : it fired somewhere in the turn but not first
    not_fired      : it never fired

    The followed/violated keys are retained with their original meaning
    (followed == fired-first) so existing callers and tests are unaffected.
    The split exists because a single followed/violated bar scores a turn
    where the tool ran second identically to one where it never ran, which
    conflates "adhered, just not literally first" with "ignored" and makes
    the raw rate read worse than reality.
    """
    stats: dict[str, dict] = defaultdict(
        lambda: {"turns": 0, "violated": 0, "followed": 0,
                 "followed_first": 0, "followed_late": 0, "not_fired": 0}
    )
    for adv, calls in turns.items():
        if not calls:
            continue
        suggests = calls[0].get("suggests") or []
        tools = [(c.get("tool") or "") for c in calls]
        for sug in suggests:
            target = SUGGEST_TO_TOOL_PREFIX.get(sug)
            if target is None:
                continue
            s = stats[sug]
            s["turns"] += 1
            if tools[0].startswith(target):
                s["followed_first"] += 1
            elif any(t.startswith(target) for t in tools):
                s["followed_late"] += 1
            else:
                s["not_fired"] += 1
            s["followed"] = s["followed_first"]
            s["violated"] = s["followed_late"] + s["not_fired"]
    return stats


def render_table(title: str, stats: dict[str, dict]) -> str:
    if not stats:
        return f"\n{title}\n  (no advisories of this class observed)\n"
    out = [f"\n{title}"]
    out.append(f"  {'advisory':40s} {'turns':>7s} {'followed':>10s} {'violated':>10s} {'rate':>7s}")
    out.append("  " + "-" * 80)
    for adv, s in sorted(stats.items()):
        rate = s["followed"] / s["turns"] if s["turns"] else 0
        out.append(f"  {adv:40s} {s['turns']:>7d} {s['followed']:>10d} {s['violated']:>10d} {rate*100:>6.1f}%")
    return "\n".join(out) + "\n"


def render_suggest_table(title: str, stats: dict[str, dict]) -> str:
    if not stats:
        return f"\n{title}\n  (no advisories of this class observed)\n"
    out = [f"\n{title}"]
    out.append(f"  {'advisory':40s} {'turns':>6s} {'first':>6s} {'late':>6s} {'none':>6s} {'first%':>8s} {'any%':>7s}")
    out.append("  " + "-" * 92)
    for adv, s in sorted(stats.items()):
        t = s["turns"]
        first = s.get("followed_first", s["followed"])
        late = s.get("followed_late", 0)
        none = s.get("not_fired", s["violated"])
        first_pct = first / t * 100 if t else 0
        any_pct = (first + late) / t * 100 if t else 0
        out.append(f"  {adv:40s} {t:>6d} {first:>6d} {late:>6d} {none:>6d} {first_pct:>7.1f}% {any_pct:>6.1f}%")
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--since", type=str, default=None, help="ISO date, e.g. 2026-05-01")
    parser.add_argument("--session-id", dest="session_id", type=str, default=None,
                        help="filter records to a single session (matches tracker's session_id field)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    since = None
    if args.since:
        try:
            since = datetime.fromisoformat(args.since)
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
        except Exception:
            print(f"invalid --since: {args.since}", file=sys.stderr)
            return 2

    records = load_log(args.log, since, args.session_id)
    if not records:
        msg = f"no records in {args.log}"
        if args.session_id:
            msg += f" (session_id={args.session_id})"
        print(msg, file=sys.stderr)
        return 0

    turns = group_turns(records)
    skip_stats = analyze_skips(turns)
    suggest_stats = analyze_suggests_first(turns)

    if args.json:
        print(json.dumps({
            "log": str(args.log),
            "session_id": args.session_id,
            "records": len(records),
            "turns": len(turns),
            "skip_adherence": dict(skip_stats),
            "suggest_first_adherence": dict(suggest_stats),
        }, indent=2))
        return 0

    print(f"log: {args.log}")
    if args.session_id:
        print(f"session_id filter: {args.session_id}")
    print(f"records: {len(records)}   turns: {len(turns)}")
    print(render_table("skip-adherence (was the tool avoided when skip=X was in force?)", skip_stats))
    print(render_suggest_table(
        "suggest-adherence (first=fired first · late=fired but not first · none=never fired; "
        "first%=old strict rate, any%=fired at all)", suggest_stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
