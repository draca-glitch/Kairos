"""Tests for the Layer 5 future-orientation injection hook (hooks/future-state.py).

The hook reuses the temporal-future MCP for queries; these tests exercise
the gate + render logic directly with synthetic result dicts (no DB needed).
"""

import importlib.util
from pathlib import Path

_HOOK = Path(__file__).resolve().parent.parent / "hooks" / "future-state.py"
_spec = importlib.util.spec_from_file_location("future_state", _HOOK)
fs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fs)


def _result(overdue=0, due_today=0, upcoming=0, mems=0, high=0):
    od = [
        {"title": f"o{i}", "area": "brf", "priority": "high" if i < high else "low",
         "due_date": "2026-05-01", "days_until": -30}
        for i in range(overdue)
    ]
    dt = [{"title": "dt", "area": "iss", "priority": "high", "due_date": "2026-06-03", "days_until": 0}
          for _ in range(due_today)]
    up = [{"title": "up", "area": "house", "priority": "low", "due_date": "2026-06-05", "days_until": 2}
          for _ in range(upcoming)]
    return {
        "tasks": {
            "available": True,
            "counts": {"overdue": overdue, "due_today": due_today, "upcoming_in_horizon": upcoming},
            "overdue": od, "due_today": dt, "upcoming": up,
        },
        "expiring_memories": {"available": True, "count": mems},
    }


def test_silent_when_nothing_due():
    assert fs.render(_result(), widened=False) is None


def test_silent_when_only_upcoming_and_not_widened():
    # upcoming items must not surface unless the prompt is forward-looking
    assert fs.render(_result(upcoming=3), widened=False) is None


def test_emits_upcoming_when_widened():
    line = fs.render(_result(upcoming=3), widened=True)
    assert line and "next:" in line


def test_overdue_always_emits_even_without_keywords():
    line = fs.render(_result(overdue=2, high=1), widened=False)
    assert line.startswith("[obligations]")
    assert "2 overdue (1 high)" in line


def test_due_today_emits():
    line = fs.render(_result(due_today=1), widened=False)
    assert "1 due today" in line
    assert "today" in line


def test_expiring_memories_shown():
    line = fs.render(_result(overdue=1, mems=3), widened=False)
    assert "3 memory(ies) expiring" in line


def test_unavailable_tasks_is_silent():
    assert fs.render({"tasks": {"available": False}}, widened=False) is None


def test_overdue_next_uses_least_stale():
    r = _result(overdue=2)
    r["tasks"]["overdue"] = [
        {"title": "ancient", "area": "iss", "priority": "low", "days_until": -337},
        {"title": "fresh-miss", "area": "brf", "priority": "high", "days_until": -2},
    ]
    line = fs.render(r, widened=False)
    assert "next: 'fresh-miss' 2d overdue" in line
    assert "ancient" not in line


def test_upcoming_preferred_over_overdue_even_unwidened():
    line = fs.render(_result(overdue=2, upcoming=1), widened=False)
    assert "next: 'up' in 2d" in line
    assert "overdue" in line  # counts still lead the line


def test_forward_keywords_match():
    assert fs.FORWARD_KEYWORDS.search("what's left this week?")
    assert fs.FORWARD_KEYWORDS.search("imorgon ska jag fixa det")
    assert fs.FORWARD_KEYWORDS.search("any upcoming deadlines")


def test_forward_keywords_no_false_match():
    assert not fs.FORWARD_KEYWORDS.search("the cat sat on the mat")
