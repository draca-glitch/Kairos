#!/usr/bin/env python3
"""
Unit tests for hooks/temporal-routing.py, in particular the R7 word-
boundary keyword matcher. The hyphenated filename can't be imported
normally so we load it via importlib.

Run:
  python3 -m unittest tests.test_routing
"""

import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "temporal_routing", REPO_ROOT / "hooks" / "temporal-routing.py"
)
routing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(routing)


def _state(prompt: str = "", **extras) -> dict:
    base = {
        "transcript_available": True,
        "prompts_count": 5,
        "gap_seconds": 60,
        "gap_str": "1m",
        "cross_day": False,
        "cadence": "active-collaboration",
        "phase": "continuing",
        "tod": "afternoon",
        "prompt_text": prompt,
    }
    base.update(extras)
    return base


class TestR7WordBoundary(unittest.TestCase):
    """R7 must only match free-standing tokens, not substrings."""

    def test_api_inside_rapid_does_not_fire(self):
        suggests, _, _ = routing.evaluate_rules(_state("the rapid response was fast"))
        self.assertNotIn("temporal_staleness_audit-first", suggests)

    def test_new_in_inside_knew_in_does_not_fire(self):
        suggests, _, _ = routing.evaluate_rules(_state("I knew in advance"))
        self.assertNotIn("temporal_staleness_audit-first", suggests)

    def test_cost_inside_pentecost_does_not_fire(self):
        suggests, _, _ = routing.evaluate_rules(_state("Pentecost feast"))
        self.assertNotIn("temporal_staleness_audit-first", suggests)

    def test_free_standing_api_fires(self):
        suggests, _, reasons = routing.evaluate_rules(_state("graphics api docs"))
        self.assertIn("temporal_staleness_audit-first", suggests)
        self.assertTrue(any("staleness-trigger=api" in r for r in reasons))

    def test_multi_word_phrase_fires(self):
        suggests, _, reasons = routing.evaluate_rules(_state("release notes for v2"))
        self.assertIn("temporal_staleness_audit-first", suggests)
        self.assertTrue(any("staleness-trigger=release notes" in r for r in reasons))

    def test_model_version_fires(self):
        suggests, _, _ = routing.evaluate_rules(_state("which model version is current?"))
        self.assertIn("temporal_staleness_audit-first", suggests)

    def test_empty_prompt_no_fire(self):
        suggests, _, _ = routing.evaluate_rules(_state(""))
        self.assertNotIn("temporal_staleness_audit-first", suggests)


class TestRulesR1ToR6(unittest.TestCase):
    def test_r1_long_gap_suggests_memory(self):
        suggests, _, _ = routing.evaluate_rules(_state(gap_seconds=1800))
        self.assertIn("memory_search-first", suggests)

    def test_r2_cross_day_long_gap_flags_staleness(self):
        suggests, _, _ = routing.evaluate_rules(
            _state(gap_seconds=5 * 3600, cross_day=True)
        )
        self.assertIn("memory_search-first", suggests)
        self.assertIn("flag-staleness", suggests)

    def test_r3_rapid_fire_skips_overhead(self):
        _, skips, _ = routing.evaluate_rules(_state(cadence="rapid-fire"))
        self.assertIn("TaskCreate-overhead", skips)
        self.assertIn("preamble", skips)

    def test_r4_session_start_reads_claude_md(self):
        suggests, _, _ = routing.evaluate_rules(_state(phase="session-start"))
        self.assertIn("read-CLAUDE.md-first", suggests)

    def test_r5_reflective_long_prompt_write_more(self):
        long_prompt = "x" * 250
        suggests, _, _ = routing.evaluate_rules(
            _state(long_prompt, cadence="reflective-pace")
        )
        self.assertIn("write-longer-reasoning-prose", suggests)

    def test_r6_late_night_resumed_confirms(self):
        suggests, _, _ = routing.evaluate_rules(
            _state(tod="late-night", cadence="resumed-after-break")
        )
        self.assertIn("confirm-before-destructive", suggests)

    def test_no_rule_fires_silent(self):
        suggests, skips, _ = routing.evaluate_rules(_state())
        self.assertEqual(suggests, [])
        self.assertEqual(skips, [])


class TestLoggedOnlyDemotion(unittest.TestCase):
    def test_r8_still_evaluated_for_state_file(self):
        # R8 must still fire in evaluate_rules so the tracker/state file keeps
        # measuring it; only the emitted line suppresses it.
        suggests, _, reasons = routing.evaluate_rules(_state("any upcoming deadline"))
        self.assertIn("temporal_future_query-first", suggests)
        self.assertTrue(any(r.startswith("future-trigger=") for r in reasons))

    def test_visible_drops_demoted_suggest_and_its_reason(self):
        suggests = ["memory_search-first", "temporal_future_query-first"]
        reasons = ["gap=31m", "future-trigger=upcoming"]
        vs, vr = routing.visible_advisories(suggests, reasons)
        self.assertIn("memory_search-first", vs)
        self.assertNotIn("temporal_future_query-first", vs)
        self.assertEqual(vr, ["gap=31m"])

    def test_visible_drops_demoted_staleness_and_its_reason(self):
        suggests = ["memory_search-first", "temporal_staleness_audit-first"]
        reasons = ["gap=31m", "staleness-trigger=api"]
        vs, vr = routing.visible_advisories(suggests, reasons)
        self.assertNotIn("temporal_staleness_audit-first", vs)
        self.assertEqual(vr, ["gap=31m"])

    def test_r7_still_evaluated_for_state_file(self):
        suggests, _, reasons = routing.evaluate_rules(_state("how do I use this api"))
        self.assertIn("temporal_staleness_audit-first", suggests)
        self.assertTrue(any(r.startswith("staleness-trigger=") for r in reasons))

    def test_visible_passes_non_demoted_through(self):
        suggests = ["memory_search-first", "read-CLAUDE.md-first"]
        reasons = ["gap=31m", "phase=session-start"]
        vs, vr = routing.visible_advisories(suggests, reasons)
        self.assertEqual(vs, suggests)
        self.assertEqual(vr, reasons)


if __name__ == "__main__":
    unittest.main(verbosity=2)
