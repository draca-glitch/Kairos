#!/usr/bin/env python3
"""
Unit tests for mcp/temporal-future.py (Layer 5).

Strategy: build a temporary sqlite tasks database with rows at known
relative-to-today dates, then exercise the query functions. Memory DB
is left absent in most tests to verify graceful degradation; one case
exercises both DBs together.

Run:
  python3 -m unittest tests.test_temporal_future
"""

import importlib.util
import os
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "temporal_future", REPO_ROOT / "mcp" / "temporal-future.py"
)


def _load_module(tasks_db: Path, memory_db: Path):
    """Reload the module with env vars pointing at fresh sqlite paths."""
    os.environ["KAIROS_TASKS_DB"] = str(tasks_db)
    os.environ["KAIROS_MEMORY_DB"] = str(memory_db)
    mod = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(mod)
    return mod


def _make_tasks_db(path: Path, rows: list[dict]) -> None:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            area TEXT NOT NULL,
            priority TEXT DEFAULT 'medium',
            status TEXT DEFAULT 'open',
            due_date TEXT
        )
    """)
    for r in rows:
        conn.execute(
            "INSERT INTO tasks(title, area, priority, status, due_date) VALUES (?, ?, ?, ?, ?)",
            (r["title"], r["area"], r.get("priority", "medium"), r.get("status", "open"), r.get("due_date")),
        )
    conn.commit()
    conn.close()


def _make_memory_db(path: Path, rows: list[dict]) -> None:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT,
            project TEXT,
            type TEXT DEFAULT 'fact',
            status TEXT DEFAULT 'active',
            valid_until TEXT
        )
    """)
    for r in rows:
        conn.execute(
            "INSERT INTO memories(content, project, type, status, valid_until) VALUES (?, ?, ?, ?, ?)",
            (r["content"], r.get("project", "personal"), r.get("type", "fact"),
             r.get("status", "active"), r.get("valid_until")),
        )
    conn.commit()
    conn.close()


def _iso_offset(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


class TestFutureQueryWithRealTasks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tasks_db = Path(self.tmp.name) / "tasks.db"
        self.memory_db = Path(self.tmp.name) / "missing.db"  # intentionally absent
        _make_tasks_db(self.tasks_db, [
            {"title": "Overdue high", "area": "brf", "priority": "high", "due_date": _iso_offset(-10)},
            {"title": "Overdue med", "area": "brf", "priority": "medium", "due_date": _iso_offset(-3)},
            {"title": "Due today",  "area": "brf", "priority": "medium", "due_date": _iso_offset(0)},
            {"title": "Tomorrow",   "area": "brf", "priority": "medium", "due_date": _iso_offset(1)},
            {"title": "In 5 days",  "area": "iss-seb-pdc1", "priority": "low", "due_date": _iso_offset(5)},
            {"title": "Out of horizon", "area": "brf", "priority": "low", "due_date": _iso_offset(30)},
            {"title": "Closed",     "area": "brf", "status": "done", "due_date": _iso_offset(-5)},
        ])
        self.mod = _load_module(self.tasks_db, self.memory_db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_horizon_filters_correctly(self):
        result = self.mod.tool_temporal_future_query({"horizon_days": 7})
        counts = result["tasks"]["counts"]
        self.assertEqual(counts["overdue"], 2)
        self.assertEqual(counts["due_today"], 1)
        self.assertEqual(counts["upcoming_in_horizon"], 2)

    def test_done_tasks_excluded(self):
        result = self.mod.tool_temporal_future_query({"horizon_days": 60})
        all_titles = (
            [t["title"] for t in result["tasks"]["overdue"]]
            + [t["title"] for t in result["tasks"]["due_today"]]
            + [t["title"] for t in result["tasks"]["upcoming"]]
        )
        self.assertNotIn("Closed", all_titles)

    def test_days_until_computed(self):
        result = self.mod.tool_temporal_future_query({"horizon_days": 7})
        for t in result["tasks"]["overdue"]:
            self.assertLess(t["days_until"], 0)
        for t in result["tasks"]["due_today"]:
            self.assertEqual(t["days_until"], 0)
        for t in result["tasks"]["upcoming"]:
            self.assertGreater(t["days_until"], 0)

    def test_highlights_include_overdue_count(self):
        result = self.mod.tool_temporal_future_query({"horizon_days": 7})
        joined = " ".join(result["highlights"])
        self.assertIn("overdue", joined)
        self.assertIn("high-priority", joined)

    def test_highlights_include_due_today(self):
        result = self.mod.tool_temporal_future_query({"horizon_days": 7})
        joined = " ".join(result["highlights"])
        self.assertIn("TODAY", joined)

    def test_memory_db_absent_degrades_gracefully(self):
        result = self.mod.tool_temporal_future_query({"horizon_days": 7})
        self.assertFalse(result["expiring_memories"]["available"])

    def test_horizon_clamped(self):
        # horizon_days=999 should clamp to 90
        result = self.mod.tool_temporal_future_query({"horizon_days": 999})
        self.assertEqual(result["horizon_days"], 90)


class TestObligationsFor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tasks_db = Path(self.tmp.name) / "tasks.db"
        self.memory_db = Path(self.tmp.name) / "missing.db"
        _make_tasks_db(self.tasks_db, [
            {"title": "BRF task", "area": "brf", "due_date": _iso_offset(-1)},
            {"title": "ISS task", "area": "iss-seb-pdc1", "due_date": _iso_offset(-1)},
            {"title": "House task", "area": "private-house", "due_date": _iso_offset(2)},
        ])
        self.mod = _load_module(self.tasks_db, self.memory_db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_area_filter_isolates_brf(self):
        result = self.mod.tool_temporal_obligations_for({"area": "brf", "horizon_days": 7})
        all_titles = (
            [t["title"] for t in result["tasks"]["overdue"]]
            + [t["title"] for t in result["tasks"]["upcoming"]]
        )
        self.assertIn("BRF task", all_titles)
        self.assertNotIn("ISS task", all_titles)
        self.assertNotIn("House task", all_titles)

    def test_missing_area_returns_error(self):
        result = self.mod.tool_temporal_obligations_for({"area": "", "horizon_days": 7})
        self.assertIn("error", result)


class TestExpiringMemories(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tasks_db = Path(self.tmp.name) / "missing-tasks.db"  # absent
        self.memory_db = Path(self.tmp.name) / "memory.db"
        _make_memory_db(self.memory_db, [
            {"content": "Memory that expires soon", "valid_until": _iso_offset(3)},
            {"content": "Memory expired yesterday", "valid_until": _iso_offset(-1)},
            {"content": "Memory far out", "valid_until": _iso_offset(60)},
            {"content": "Memory with no expiry", "valid_until": None},
            {"content": "Archived memory", "valid_until": _iso_offset(3), "status": "archived"},
        ])
        self.mod = _load_module(self.tasks_db, self.memory_db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_in_window_active_memories_returned(self):
        result = self.mod.tool_temporal_future_query({"horizon_days": 14})
        mems = result["expiring_memories"]
        self.assertTrue(mems["available"])
        self.assertEqual(mems["count"], 1)
        self.assertIn("expires soon", mems["expiring"][0]["preview"])

    def test_tasks_db_absent_degrades(self):
        result = self.mod.tool_temporal_future_query({"horizon_days": 7})
        self.assertFalse(result["tasks"]["available"])


class TestBothDbsAbsent(unittest.TestCase):
    def test_both_missing_returns_empty_but_no_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = _load_module(Path(tmp) / "no-tasks.db", Path(tmp) / "no-memory.db")
            result = mod.tool_temporal_future_query({})
            self.assertFalse(result["tasks"]["available"])
            self.assertFalse(result["expiring_memories"]["available"])
            self.assertEqual(result["highlights"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
