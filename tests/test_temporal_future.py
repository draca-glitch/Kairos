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


def _add_memory_links(path: Path, links: list[tuple[int, int, str]]) -> None:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE memory_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            relation_type TEXT NOT NULL DEFAULT 'related'
        )
    """)
    conn.executemany(
        "INSERT INTO memory_links(source_id, target_id, relation_type) VALUES (?, ?, ?)", links)
    conn.commit()
    conn.close()


class TestAreaMatching(unittest.TestCase):
    """An area is an exact name or a prefix of one hyphen-separated part; an
    area that selects nothing is an error, never an empty result."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tasks_db = Path(self.tmp.name) / "tasks.db"
        _make_tasks_db(self.tasks_db, [
            {"title": "Site A late", "area": "work-site-a", "due_date": _iso_offset(-2)},
            {"title": "Site B late", "area": "work-site-b", "due_date": _iso_offset(-1)},
            {"title": "Site B soon", "area": "work-site-b", "due_date": _iso_offset(3)},
            {"title": "Depot late", "area": "work-depot", "due_date": _iso_offset(-4)},
            {"title": "Home late", "area": "home", "due_date": _iso_offset(-1)},
            {"title": "Home ext late", "area": "home-garden", "due_date": _iso_offset(-1)},
            {"title": "Archive only", "area": "archive", "status": "done", "due_date": _iso_offset(-9)},
        ])
        self.mod = _load_module(self.tasks_db, Path(self.tmp.name) / "missing.db")

    def tearDown(self):
        self.tmp.cleanup()

    def _titles(self, result):
        tasks = result["tasks"]
        return sorted(t["title"] for t in tasks["overdue"] + tasks["due_today"] + tasks["upcoming"])

    def test_leading_part_selects_the_family(self):
        result = self.mod.tool_temporal_obligations_for({"area": "work"})
        self.assertEqual(result["matched_areas"], ["work-depot", "work-site-a", "work-site-b"])
        self.assertEqual(result["tasks"]["counts"]["overdue"], 3)
        self.assertEqual(result["tasks"]["counts"]["upcoming_in_horizon"], 1)

    def test_inner_part_selects_across_the_family(self):
        result = self.mod.tool_temporal_obligations_for({"area": "site"})
        self.assertEqual(result["matched_areas"], ["work-site-a", "work-site-b"])
        self.assertEqual(self._titles(result), ["Site A late", "Site B late", "Site B soon"])

    def test_multi_part_prefix(self):
        result = self.mod.tool_temporal_obligations_for({"area": "work-site"})
        self.assertEqual(result["matched_areas"], ["work-site-a", "work-site-b"])

    def test_exact_area_wins_over_its_longer_siblings(self):
        result = self.mod.tool_temporal_obligations_for({"area": "home"})
        self.assertEqual(result["matched_areas"], ["home"])
        self.assertEqual(self._titles(result), ["Home late"])

    def test_match_is_case_insensitive_and_trimmed(self):
        result = self.mod.tool_temporal_obligations_for({"area": "  SITE "})
        self.assertEqual(result["matched_areas"], ["work-site-a", "work-site-b"])

    def test_mid_word_fragment_does_not_match(self):
        result = self.mod.tool_temporal_obligations_for({"area": "ork"})
        self.assertIn("error", result)

    def test_unknown_area_is_an_error_listing_known_areas(self):
        result = self.mod.tool_temporal_obligations_for({"area": "nowhere"})
        self.assertIn("error", result)
        self.assertNotIn("tasks", result)
        self.assertIn("work-site-a", result["error"])
        self.assertEqual(result["known_areas"],
                         ["archive", "home", "home-garden", "work-depot", "work-site-a", "work-site-b"])

    def test_area_with_only_closed_tasks_is_known_and_empty(self):
        result = self.mod.tool_temporal_obligations_for({"area": "archive"})
        self.assertNotIn("error", result)
        self.assertEqual(result["tasks"]["counts"]["overdue"], 0)

    def test_unknown_area_is_flagged_as_error_on_the_wire(self):
        import json
        import subprocess
        import sys
        env = {**os.environ, "KAIROS_TASKS_DB": str(self.tasks_db),
               "KAIROS_MEMORY_DB": str(Path(self.tmp.name) / "missing.db")}
        call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "temporal_obligations_for", "arguments": {"area": "nowhere"}}}
        proc = subprocess.run([sys.executable, str(REPO_ROOT / "mcp" / "temporal-future.py")],
                              input=json.dumps(call) + "\n", capture_output=True, text=True,
                              timeout=60, env=env)
        result = json.loads(proc.stdout.splitlines()[0])["result"]
        self.assertTrue(result["isError"])


class TestCountsAreTotals(unittest.TestCase):
    """Lists stop at LIST_LIMIT; counts and the highlight must not."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tasks_db = Path(self.tmp.name) / "tasks.db"
        rows = [{"title": f"Late {i}", "area": "a", "due_date": _iso_offset(-(i + 1)),
                 "priority": "high" if i % 2 == 0 else "medium"} for i in range(60)]
        # Not dates: these compare as strings and used to count as overdue forever.
        rows += [{"title": "Empty date", "area": "a", "due_date": ""},
                 {"title": "Text date", "area": "a", "due_date": "0-soon"}]
        _make_tasks_db(self.tasks_db, rows)
        self.mod = _load_module(self.tasks_db, Path(self.tmp.name) / "missing.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_count_exceeds_the_list_cap(self):
        tasks = self.mod.tool_temporal_future_query({})["tasks"]
        self.assertEqual(len(tasks["overdue"]), self.mod.LIST_LIMIT)
        self.assertEqual(tasks["counts"]["overdue"], 60)
        self.assertEqual(tasks["counts"]["overdue_high"], 30)

    def test_the_cap_drops_the_longest_dead_and_keeps_oldest_first_order(self):
        overdue = self.mod.tool_temporal_future_query({})["tasks"]["overdue"]
        self.assertEqual(overdue[-1]["title"], "Late 0")       # missed yesterday
        self.assertEqual(overdue[0]["title"], "Late 49")
        days = [t["days_until"] for t in overdue]
        self.assertEqual(days, sorted(days))

    def test_highlight_reports_the_total(self):
        highlights = self.mod.tool_temporal_future_query({})["highlights"]
        self.assertIn("60 overdue task(s) (30 high-priority)", highlights)

    def test_non_date_due_dates_are_not_overdue(self):
        tasks = self.mod.tool_temporal_future_query({"horizon_days": 90})["tasks"]
        titles = [t["title"] for t in tasks["overdue"] + tasks["due_today"] + tasks["upcoming"]]
        self.assertNotIn("Empty date", titles)
        self.assertNotIn("Text date", titles)

    def test_horizon_tolerates_garbage(self):
        self.assertEqual(self.mod.tool_temporal_future_query({"horizon_days": "soon"})["horizon_days"], 7)
        self.assertEqual(self.mod.tool_temporal_future_query({"horizon_days": None})["horizon_days"], 7)


class TestMemoryValidity(unittest.TestCase):
    """Expiring = today or later inside the window. Expired-but-active is a
    separate capped list. A superseded memory is in neither."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.memory_db = Path(self.tmp.name) / "memory.db"
        rows = [
            {"content": "expires today", "valid_until": _iso_offset(0)},               # 1
            {"content": "expires in window", "valid_until": _iso_offset(5)},           # 2
            {"content": "superseded today", "valid_until": _iso_offset(0)},            # 3
            {"content": "superseded last week", "valid_until": _iso_offset(-7)},       # 4
            {"content": "marked superseded_by", "valid_until": _iso_offset(-3)},       # 5
            {"content": "archived and expired", "valid_until": _iso_offset(-2), "status": "archived"},  # 6
            {"content": "successor, no expiry", "valid_until": None},                  # 7
            {"content": "datetime expiry in window", "valid_until": _iso_offset(2) + " 09:30:00"},  # 8
            {"content": "only related-linked, expired", "valid_until": _iso_offset(-1)},  # 9
        ]
        rows += [{"content": f"stale {i}", "valid_until": _iso_offset(-(10 + i))} for i in range(8)]  # 10-17
        _make_memory_db(self.memory_db, rows)
        _add_memory_links(self.memory_db, [
            (3, 7, "evolves"), (4, 7, "evolves"), (5, 7, "superseded_by"),
            (9, 7, "related"),
            (7, 2, "evolves"),          # incoming to 2: being a successor is not being superseded
        ])
        self.mod = _load_module(Path(self.tmp.name) / "missing-tasks.db", self.memory_db)
        self.mems = self.mod.tool_temporal_future_query({"horizon_days": 14})["expiring_memories"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_window_includes_today_and_excludes_superseded(self):
        previews = [m["preview"] for m in self.mems["expiring"]]
        self.assertEqual(previews, ["expires today", "datetime expiry in window", "expires in window"])
        self.assertEqual(self.mems["count"], 3)
        self.assertEqual(self.mems["expiring"][0]["days_until"], 0)

    def test_expired_active_is_counted_and_capped_newest_first(self):
        expired = self.mems["expired_active"]
        self.assertEqual(expired["count"], 9)          # memory 9 plus the eight stale ones
        self.assertEqual(len(expired["newest"]), self.mod.EXPIRED_ACTIVE_SHOWN)
        self.assertEqual(expired["newest"][0]["preview"], "only related-linked, expired")
        days = [m["days_until"] for m in expired["newest"]]
        self.assertEqual(days, sorted(days, reverse=True))
        self.assertTrue(all(d < 0 for d in days))

    def test_superseded_and_archived_are_reported_nowhere(self):
        seen = [m["preview"] for m in self.mems["expiring"] + self.mems["expired_active"]["newest"]]
        for gone in ("superseded today", "superseded last week", "marked superseded_by",
                     "archived and expired"):
            self.assertNotIn(gone, seen)

    def test_highlight_counts_only_the_window(self):
        result = self.mod.tool_temporal_future_query({"horizon_days": 14})
        self.assertIn("3 memory(ies) expiring in window", result["highlights"])

    def test_store_without_a_links_table_still_answers(self):
        plain = Path(self.tmp.name) / "plain.db"
        _make_memory_db(plain, [{"content": "old", "valid_until": _iso_offset(-1)},
                                {"content": "soon", "valid_until": _iso_offset(1)}])
        mod = _load_module(Path(self.tmp.name) / "missing-tasks.db", plain)
        mems = mod.tool_temporal_future_query({})["expiring_memories"]
        self.assertTrue(mems["available"])
        self.assertEqual(mems["count"], 1)
        self.assertEqual(mems["expired_active"]["count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
