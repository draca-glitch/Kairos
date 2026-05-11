#!/usr/bin/env python3
"""
Table-driven unit tests for temporal_lib primitives.

Run:
  python3 -m unittest tests/test_temporal_lib.py
  python3 tests/test_temporal_lib.py
"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS_DIR))

from temporal_lib import (
    classify_cadence,
    classify_phase,
    humanize_gap,
    tod_bucket,
    is_real_user_prompt,
    is_task_notification,
    parse_payload,
)


class TestClassifyCadence(unittest.TestCase):
    def test_session_start_when_no_gaps(self):
        self.assertEqual(classify_cadence([]), "session-start")

    def test_very_rapid_fire_under_30s(self):
        for g in [0, 5, 15, 29]:
            self.assertEqual(classify_cadence([g]), "very-rapid-fire", g)

    def test_rapid_fire_needs_history(self):
        self.assertEqual(classify_cadence([45, 60, 80]), "rapid-fire")
        self.assertEqual(classify_cadence([45]), "active-collaboration")

    def test_active_collaboration_range(self):
        for g in [60, 120, 200, 299]:
            self.assertEqual(classify_cadence([g]), "active-collaboration", g)

    def test_reflective_pace_range(self):
        for g in [300, 600, 1500, 1799]:
            self.assertEqual(classify_cadence([g]), "reflective-pace", g)

    def test_spaced_work_above_30m(self):
        for g in [1800, 3000, 7000]:
            self.assertEqual(classify_cadence([g]), "spaced-work", g)

    def test_resumed_after_break_2h(self):
        self.assertEqual(classify_cadence([2 * 3600]), "resumed-after-break")
        self.assertEqual(classify_cadence([5 * 3600]), "resumed-after-break")

    def test_resumed_after_long_gap_6h(self):
        self.assertEqual(classify_cadence([6 * 3600]), "resumed-after-long-gap")
        self.assertEqual(classify_cadence([24 * 3600]), "resumed-after-long-gap")


class TestClassifyPhase(unittest.TestCase):
    def test_session_start(self):
        self.assertEqual(classify_phase([], False), "session-start")
        self.assertEqual(classify_phase([], True), "session-start")

    def test_continuing_short_gap(self):
        self.assertEqual(classify_phase([60], False), "continuing")
        self.assertEqual(classify_phase([3599], False), "continuing")

    def test_resumed_after_pause_1h(self):
        self.assertEqual(classify_phase([3600], False), "resumed-after-pause")
        self.assertEqual(classify_phase([5 * 3600], False), "resumed-after-pause")

    def test_interruption_pivot_6h_same_day(self):
        self.assertEqual(classify_phase([6 * 3600], False), "interruption-pivot")
        self.assertEqual(classify_phase([10 * 3600], False), "interruption-pivot")

    def test_resumed_after_overnight_cross_day(self):
        self.assertEqual(classify_phase([5 * 3600], True), "resumed-after-overnight")
        self.assertEqual(classify_phase([12 * 3600], True), "resumed-after-overnight")

    def test_short_gap_cross_day_still_continuing(self):
        # cross_day=True but gap < 4h falls through to short-gap rules
        self.assertEqual(classify_phase([1800], True), "continuing")


class TestTodBucket(unittest.TestCase):
    def _at(self, hour: int) -> datetime:
        return datetime(2026, 5, 11, hour, 0, tzinfo=timezone.utc).astimezone()

    def test_all_buckets(self):
        # Use a fixed UTC offset comparison via plain datetime construction
        cases = {
            "late-night": [0, 2, 4],
            "early-morning": [5, 7, 8],
            "morning": [9, 10, 11],
            "midday": [12, 13],
            "afternoon": [14, 16, 17],
            "evening": [18, 20, 21],
            "night": [22, 23],
        }
        for bucket, hours in cases.items():
            for h in hours:
                dt = datetime(2026, 5, 11, h, 0)
                self.assertEqual(tod_bucket(dt), bucket, f"hour={h}")


class TestHumanizeGap(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(humanize_gap(0), "0s")
        self.assertEqual(humanize_gap(45), "45s")
        self.assertEqual(humanize_gap(59), "59s")

    def test_minutes(self):
        self.assertEqual(humanize_gap(60), "1m")
        self.assertEqual(humanize_gap(125), "2m")
        self.assertEqual(humanize_gap(3599), "59m")

    def test_hours(self):
        self.assertEqual(humanize_gap(3600), "1h")
        self.assertEqual(humanize_gap(3600 + 1020), "1h17m")
        self.assertEqual(humanize_gap(11 * 3600 + 1020), "11h17m")


class TestPayloadParsing(unittest.TestCase):
    def test_parse_payload_valid(self):
        self.assertEqual(parse_payload('{"a":1}'), {"a": 1})

    def test_parse_payload_invalid_returns_empty(self):
        self.assertEqual(parse_payload("not json"), {})
        self.assertEqual(parse_payload(""), {})

    def test_is_task_notification(self):
        self.assertTrue(is_task_notification({"prompt": "<task-notification>foo</task-notification>"}))
        self.assertFalse(is_task_notification({"prompt": "regular prompt"}))
        self.assertFalse(is_task_notification({}))


class TestIsRealUserPrompt(unittest.TestCase):
    def test_string_content(self):
        e = {"type": "user", "message": {"role": "user", "content": "hello"}}
        self.assertTrue(is_real_user_prompt(e))

    def test_task_notification_filtered(self):
        e = {"type": "user", "message": {"role": "user", "content": "<task-notification>x</task-notification>"}}
        self.assertFalse(is_real_user_prompt(e))

    def test_tool_result_filtered(self):
        e = {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "content": "stuff"}
        ]}}
        self.assertFalse(is_real_user_prompt(e))

    def test_text_block_accepted(self):
        e = {"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": "hello"}
        ]}}
        self.assertTrue(is_real_user_prompt(e))

    def test_assistant_event_rejected(self):
        e = {"type": "assistant", "message": {"role": "assistant", "content": "x"}}
        self.assertFalse(is_real_user_prompt(e))


if __name__ == "__main__":
    unittest.main(verbosity=2)
