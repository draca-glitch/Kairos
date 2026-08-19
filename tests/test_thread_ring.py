#!/usr/bin/env python3
"""
Unit tests for the thread-ring history backend (Codex adapter substrate).

Run:
  python3 -m unittest tests/test_thread_ring.py
  python3 tests/test_thread_ring.py
"""

import contextlib
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS_DIR))

import temporal_lib
from temporal_lib import (
    RING_LIMIT,
    compute_state,
    ring_load,
    ring_record,
    resolve_thread_id,
)


@contextlib.contextmanager
def fake_home():
    """Point the process home at an empty temp dir, cross-platform.

    temporal_lib resolves home via Path.home(), which reads HOME on POSIX
    but USERPROFILE on Windows (ntpath.expanduser never consults HOME), so
    both must be patched or the fixture silently escapes into the real
    ~/.claude/projects on Windows.
    """
    keys = ("HOME", "USERPROFILE")
    old = {k: os.environ.get(k) for k in keys}
    with tempfile.TemporaryDirectory() as tmp:
        for k in keys:
            os.environ[k] = tmp
        try:
            yield Path(tmp)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class RingTestCase(unittest.TestCase):
    """Shared fixture: isolated state dir + ring backend selected."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_env = {
            k: os.environ.get(k)
            for k in ("CLAUDE_KIT_STATE_DIR", "KAIROS_HISTORY_BACKEND", "KAIROS_THREAD_ID")
        }
        os.environ["CLAUDE_KIT_STATE_DIR"] = self._tmp.name
        os.environ["KAIROS_HISTORY_BACKEND"] = "ring"
        os.environ.pop("KAIROS_THREAD_ID", None)

    def tearDown(self):
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def seed(self, thread_id: str, offsets_seconds: list[float]):
        """Record one timestamp per offset (seconds before now), oldest first."""
        now = datetime.now(timezone.utc)
        for off in sorted(offsets_seconds, reverse=True):
            ring_record(thread_id, when=now - timedelta(seconds=off))

    def ring_dir(self) -> Path:
        return Path(self._tmp.name) / temporal_lib.RING_DIR_NAME


class TestRingStore(RingTestCase):
    def test_empty_ring_is_session_start(self):
        state = compute_state({"session_id": "thread-a", "prompt": "hej"})
        self.assertTrue(state["transcript_available"])
        self.assertEqual(state["prompts_count"], 0)
        self.assertEqual(state["phase"], "session-start")
        self.assertEqual(state["cadence"], "session-start")

    def test_second_prompt_after_two_minutes_is_continuing(self):
        self.seed("thread-a", [120])
        state = compute_state({"session_id": "thread-a", "prompt": "hej"})
        self.assertEqual(state["prompts_count"], 1)
        self.assertEqual(state["phase"], "continuing")
        self.assertEqual(state["cadence"], "active-collaboration")
        self.assertAlmostEqual(state["gap_seconds"], 120, delta=5)

    def test_threads_are_isolated(self):
        self.seed("thread-a", [120])
        state_b = compute_state({"session_id": "thread-b", "prompt": "hej"})
        self.assertEqual(state_b["prompts_count"], 0)
        self.assertEqual(state_b["phase"], "session-start")

    def test_very_rapid_fire(self):
        self.seed("thread-a", [10, 40, 70])
        state = compute_state({"session_id": "thread-a", "prompt": "hej"})
        self.assertEqual(state["cadence"], "very-rapid-fire")
        self.assertEqual(state["phase"], "continuing")

    def test_long_gap_classifies_as_interruption_pivot(self):
        self.seed("thread-a", [7 * 3600])
        state = compute_state({"session_id": "thread-a", "prompt": "hej"})
        self.assertEqual(state["cadence"], "resumed-after-long-gap")
        self.assertIn(state["phase"], ("interruption-pivot", "resumed-after-overnight"))

    def test_cross_day_overnight(self):
        now_local = datetime.now(timezone.utc).astimezone()
        yesterday_evening = (now_local - timedelta(days=1)).replace(
            hour=21, minute=0, second=0, microsecond=0
        )
        gap = (now_local - yesterday_evening).total_seconds()
        if gap < 4 * 3600:
            self.skipTest("local clock too close to yesterday evening for this fixture")
        ring_record("thread-a", when=yesterday_evening.astimezone(timezone.utc))
        state = compute_state({"session_id": "thread-a", "prompt": "hej"})
        self.assertTrue(state["cross_day"])
        self.assertEqual(state["phase"], "resumed-after-overnight")

    def test_corrupt_state_degrades_to_session_start(self):
        self.seed("thread-a", [120])
        ring_file = next(self.ring_dir().glob("*.json"))
        ring_file.write_text("{not json", encoding="utf-8")
        state = compute_state({"session_id": "thread-a", "prompt": "hej"})
        self.assertEqual(state["prompts_count"], 0)
        self.assertEqual(state["phase"], "session-start")
        ring_record("thread-a")
        self.assertEqual(len(ring_load("thread-a")), 1)

    def test_ring_capped_at_limit(self):
        self.seed("thread-a", list(range(60, 60 + (RING_LIMIT + 5) * 10, 10)))
        self.assertEqual(len(ring_load("thread-a")), RING_LIMIT)

    def test_record_without_thread_id_is_noop(self):
        ring_record("")
        self.assertFalse(self.ring_dir().exists())

    def test_thread_id_never_hits_filesystem_raw(self):
        hostile = "../../../etc/passwd"
        ring_record(hostile)
        files = list(self.ring_dir().glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertNotIn("..", files[0].name)
        self.assertEqual(len(ring_load(hostile)), 1)

    def test_stale_rings_pruned_on_record(self):
        self.seed("old-thread", [120])
        old_file = next(self.ring_dir().glob("*.json"))
        stale = time.time() - temporal_lib.RING_STALE_SECONDS - 3600
        os.utime(old_file, (stale, stale))
        ring_record("fresh-thread")
        self.assertFalse(old_file.exists())
        self.assertEqual(len(ring_load("fresh-thread")), 1)

    def test_naive_timestamps_are_ignored(self):
        self.seed("thread-a", [120])
        ring_file = next(self.ring_dir().glob("*.json"))
        data = json.loads(ring_file.read_text(encoding="utf-8"))
        data["timestamps"].append("2026-08-18T08:00:00")
        ring_file.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(len(ring_load("thread-a")), 1)


class TestBackendSelection(RingTestCase):
    def test_default_backend_ignores_ring(self):
        self.seed("thread-a", [120])
        os.environ["KAIROS_HISTORY_BACKEND"] = "transcript"
        with fake_home():
            state = compute_state({"session_id": "thread-a", "prompt": "hej"})
        self.assertFalse(state["transcript_available"])
        self.assertEqual(state["phase"], "session-start")

    def test_resolve_thread_id_precedence(self):
        self.assertEqual(resolve_thread_id({"session_id": "abc"}), "abc")
        os.environ["KAIROS_THREAD_ID"] = "env-thread"
        self.assertEqual(resolve_thread_id({}), "env-thread")
        self.assertEqual(resolve_thread_id({"session_id": "abc"}), "abc")
        self.assertEqual(resolve_thread_id(None), "env-thread")


if __name__ == "__main__":
    unittest.main()
