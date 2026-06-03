#!/usr/bin/env python3
"""
Unit tests for analyze-routing-adherence.py.

Covers: group_turns, analyze_skips, analyze_suggests_first, load_log
(with synthetic JSONL fixtures in a tempdir).

Run:
  python3 -m unittest tests.test_adherence
"""

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "analyze_routing_adherence", REPO_ROOT / "analyze-routing-adherence.py"
)
adherence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adherence)


def _rec(**kw):
    """Build a tracker record with sensible defaults."""
    base = {
        "ts": "2026-05-11T19:00:00+02:00",
        "session_id": "s1",
        "tool": "Bash",
        "advisory_ts": "2026-05-11T19:00:00+02:00",
        "suggests": [],
        "skips": [],
        "cadence": "active-collaboration",
        "phase": "continuing",
        "gap_str": "1m",
    }
    base.update(kw)
    return base


class TestGroupTurns(unittest.TestCase):
    def test_groups_by_advisory_ts(self):
        records = [
            _rec(advisory_ts="A", tool="Read"),
            _rec(advisory_ts="A", tool="Bash"),
            _rec(advisory_ts="B", tool="Edit"),
        ]
        turns = adherence.group_turns(records)
        self.assertEqual(len(turns), 2)
        self.assertEqual(len(turns["A"]), 2)
        self.assertEqual(len(turns["B"]), 1)

    def test_missing_advisory_bucketed(self):
        turns = adherence.group_turns([_rec(advisory_ts=None)])
        self.assertIn("<no-advisory>", turns)

    def test_calls_sorted_by_ts(self):
        records = [
            _rec(advisory_ts="A", ts="2026-05-11T19:00:30+02:00", tool="B"),
            _rec(advisory_ts="A", ts="2026-05-11T19:00:10+02:00", tool="A"),
            _rec(advisory_ts="A", ts="2026-05-11T19:00:20+02:00", tool="M"),
        ]
        turns = adherence.group_turns(records)
        order = [c["tool"] for c in turns["A"]]
        self.assertEqual(order, ["A", "M", "B"])


class TestAnalyzeSkips(unittest.TestCase):
    def test_skip_followed_when_tool_absent(self):
        turns = {"A": [_rec(skips=["TaskCreate-overhead"], tool="Bash")]}
        stats = adherence.analyze_skips(turns)
        self.assertEqual(stats["TaskCreate-overhead"]["turns"], 1)
        self.assertEqual(stats["TaskCreate-overhead"]["followed"], 1)
        self.assertEqual(stats["TaskCreate-overhead"]["violated"], 0)

    def test_skip_violated_when_tool_called(self):
        turns = {"A": [
            _rec(skips=["TaskCreate-overhead"], tool="Bash"),
            _rec(skips=["TaskCreate-overhead"], tool="TaskCreate"),
        ]}
        stats = adherence.analyze_skips(turns)
        self.assertEqual(stats["TaskCreate-overhead"]["violated"], 1)
        self.assertEqual(stats["TaskCreate-overhead"]["followed"], 0)

    def test_advisory_only_skip_ignored(self):
        # "preamble" maps to None in SKIP_TO_TOOL_PREFIX, not a real tool
        turns = {"A": [_rec(skips=["preamble"], tool="Bash")]}
        stats = adherence.analyze_skips(turns)
        self.assertNotIn("preamble", stats)

    def test_no_skips_no_stats(self):
        turns = {"A": [_rec(tool="Bash")]}
        self.assertEqual(adherence.analyze_skips(turns), {})

    def test_multiple_skips_in_one_turn(self):
        turns = {"A": [_rec(skips=["TaskCreate-overhead", "preamble"], tool="Bash")]}
        stats = adherence.analyze_skips(turns)
        self.assertEqual(stats["TaskCreate-overhead"]["followed"], 1)


class TestAnalyzeSuggestsFirst(unittest.TestCase):
    def test_suggest_followed_when_target_is_first_tool(self):
        turns = {"A": [
            _rec(suggests=["memory_search-first"], tool="mcp__agent-memory__memory_search"),
            _rec(suggests=["memory_search-first"], tool="Bash"),
        ]}
        stats = adherence.analyze_suggests_first(turns)
        self.assertEqual(stats["memory_search-first"]["followed"], 1)

    def test_suggest_violated_when_other_tool_first(self):
        turns = {"A": [
            _rec(suggests=["memory_search-first"], tool="Bash"),
            _rec(suggests=["memory_search-first"], tool="mcp__agent-memory__memory_search"),
        ]}
        stats = adherence.analyze_suggests_first(turns)
        self.assertEqual(stats["memory_search-first"]["violated"], 1)
        self.assertEqual(stats["memory_search-first"]["followed"], 0)

    def test_advisory_only_suggest_ignored(self):
        # "flag-staleness" has no concrete target tool
        turns = {"A": [_rec(suggests=["flag-staleness"], tool="Bash")]}
        stats = adherence.analyze_suggests_first(turns)
        self.assertNotIn("flag-staleness", stats)

    def test_r7_suggest_target(self):
        turns = {"A": [_rec(
            suggests=["temporal_staleness_audit-first"],
            tool="mcp__temporal-staleness__temporal_staleness_audit",
        )]}
        stats = adherence.analyze_suggests_first(turns)
        self.assertEqual(stats["temporal_staleness_audit-first"]["followed"], 1)

    def test_suggest_followed_late_when_target_not_first(self):
        turns = {"A": [
            _rec(suggests=["memory_search-first"], tool="Bash"),
            _rec(suggests=["memory_search-first"], tool="mcp__agent-memory__memory_search"),
        ]}
        stats = adherence.analyze_suggests_first(turns)
        self.assertEqual(stats["memory_search-first"]["followed_first"], 0)
        self.assertEqual(stats["memory_search-first"]["followed_late"], 1)
        self.assertEqual(stats["memory_search-first"]["not_fired"], 0)

    def test_suggest_not_fired_when_target_absent(self):
        turns = {"A": [
            _rec(suggests=["memory_search-first"], tool="Bash"),
            _rec(suggests=["memory_search-first"], tool="Read"),
        ]}
        stats = adherence.analyze_suggests_first(turns)
        self.assertEqual(stats["memory_search-first"]["not_fired"], 1)
        self.assertEqual(stats["memory_search-first"]["followed_late"], 0)
        self.assertEqual(stats["memory_search-first"]["violated"], 1)

    def test_suggest_legacy_keys_preserved(self):
        # followed == fired-first, violated == late + not_fired
        turns = {"A": [_rec(suggests=["memory_search-first"], tool="mcp__agent-memory__memory_search")]}
        stats = adherence.analyze_suggests_first(turns)
        self.assertEqual(stats["memory_search-first"]["followed_first"], 1)
        self.assertEqual(stats["memory_search-first"]["followed"], 1)


class TestLoadLog(unittest.TestCase):
    def _write_log(self, records):
        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w")
        for r in records:
            tmp.write(json.dumps(r) + "\n")
        tmp.close()
        return Path(tmp.name)

    def test_load_all_records(self):
        path = self._write_log([_rec(tool="A"), _rec(tool="B")])
        out = adherence.load_log(path, since=None, session_id=None)
        self.assertEqual(len(out), 2)

    def test_session_id_filter(self):
        path = self._write_log([
            _rec(session_id="s1", tool="A"),
            _rec(session_id="s2", tool="B"),
            _rec(session_id="s1", tool="C"),
        ])
        out = adherence.load_log(path, since=None, session_id="s1")
        self.assertEqual([r["tool"] for r in out], ["A", "C"])

    def test_since_filter(self):
        path = self._write_log([
            _rec(ts="2026-05-10T10:00:00+02:00", tool="A"),
            _rec(ts="2026-05-11T10:00:00+02:00", tool="B"),
        ])
        out = adherence.load_log(
            path, since=datetime(2026, 5, 11, tzinfo=timezone.utc), session_id=None
        )
        self.assertEqual([r["tool"] for r in out], ["B"])

    def test_corrupt_lines_skipped(self):
        path = self._write_log([_rec(tool="A")])
        with open(path, "a") as f:
            f.write("this is not json\n")
            f.write(json.dumps(_rec(tool="C")) + "\n")
        out = adherence.load_log(path, since=None, session_id=None)
        self.assertEqual([r["tool"] for r in out], ["A", "C"])

    def test_missing_file_empty(self):
        out = adherence.load_log(Path("/nonexistent.jsonl"), since=None, session_id=None)
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
