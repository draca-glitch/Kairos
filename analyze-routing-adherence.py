#!/usr/bin/env python3
"""
Compute adherence statistics over temporal-routing-log.jsonl.

For each prompt-turn (identified by advisory_ts) the temporal-routing
hook emitted some combination of `suggests` and `skips`. The PostToolUse
tracker recorded which tools the model actually called during that turn.

This script joins the two streams and answers, per advisory class:
  - When skip=X was in force, how often did the model still call X?
  - When suggest=Y-first was in force, did Y actually fire before any
    other tool in the turn?

Output: a table to stdout. Exit 0 always (read-only).

Usage:
  ./analyze-routing-adherence.py
  ./analyze-routing-adherence.py --log /custom/path.jsonl
  ./analyze-routing-adherence.py --since 2026-05-01
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
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
    "flag-staleness": None,
    "extended-thinking-ok": None,
    "write-longer-reasoning-prose": None,
    "confirm-before-destructive": None,
}


def load_log(path: Path, since: datetime | None) -> list[dict]:
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
            records.append(r)
    return records


def group_turns(records: list[dict]) -> dict[str, list[dict]]:
    turns: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        adv = r.get("advisory_ts") or "<no-advisory>"
        turns[adv].append(r)
    for adv in turns:
        turns[adv].sort(key=lambda r: r.get("ts", ""))
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
    stats: dict[str, dict] = defaultdict(lambda: {"turns": 0, "violated": 0, "followed": 0})
    for adv, calls in turns.items():
        if not calls:
            continue
        suggests = calls[0].get("suggests") or []
        for sug in suggests:
            target = SUGGEST_TO_TOOL_PREFIX.get(sug)
            if target is None:
                continue
            stats[sug]["turns"] += 1
            first_tool = (calls[0].get("tool") or "")
            followed = first_tool.startswith(target)
            stats[sug]["followed" if followed else "violated"] += 1
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--since", type=str, default=None, help="ISO date, e.g. 2026-05-01")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    since = None
    if args.since:
        try:
            since = datetime.fromisoformat(args.since)
        except Exception:
            print(f"invalid --since: {args.since}", file=sys.stderr)
            return 2

    records = load_log(args.log, since)
    if not records:
        print(f"no records in {args.log}", file=sys.stderr)
        return 0

    turns = group_turns(records)
    skip_stats = analyze_skips(turns)
    suggest_stats = analyze_suggests_first(turns)

    if args.json:
        print(json.dumps({
            "log": str(args.log),
            "records": len(records),
            "turns": len(turns),
            "skip_adherence": dict(skip_stats),
            "suggest_first_adherence": dict(suggest_stats),
        }, indent=2))
        return 0

    print(f"log: {args.log}")
    print(f"records: {len(records)}   turns: {len(turns)}")
    print(render_table("skip-adherence (was the tool avoided when skip=X was in force?)", skip_stats))
    print(render_table("suggest-first-adherence (did suggested tool fire FIRST in the turn?)", suggest_stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
