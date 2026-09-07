"""0.13.0: decision regression set.

Each scenario builds a synthetic home (transcript, tasks DB, memory DB,
config) and runs the real UserPromptSubmit chain from hooks/ as subprocesses,
then asserts the injected context: the exact lines the model would see, and
their absence where nothing should speak. Whether the model then acts
correctly is the behavioural half, measured in production by the adherence
log; this half pins that the context itself is right and free of noise.
"""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"
CHAIN = ["temporal-state.py", "temporal-routing.py", "staleness-state.py", "future-state.py"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Scenario:
    def __init__(self, home: Path, session: str = "scenario"):
        self.home = home
        self.session = session
        (home / ".claude" / "projects" / "-root").mkdir(parents=True)
        self.state_dir = home / "state"
        self.tasks_db = home / "work" / "tasks.db"
        self.memory_db = home / "work" / "memory.db"
        self.tasks_db.parent.mkdir(parents=True)
        with sqlite3.connect(self.tasks_db) as c:
            c.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, area TEXT, "
                      "priority TEXT, status TEXT, due_date TEXT)")
        with sqlite3.connect(self.memory_db) as c:
            c.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, content TEXT, project TEXT, "
                      "type TEXT, status TEXT, valid_until TEXT)")
        cfg = home / ".config" / "kairos" / "config.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"memory_db": str(self.memory_db), "tasks_db": str(self.tasks_db)}))
        self.transcript([])

    def transcript(self, events: list[tuple[str, datetime]]) -> None:
        path = self.home / ".claude" / "projects" / "-root" / f"{self.session}.jsonl"
        lines = []
        for kind, ts in events:
            stamp = ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            if kind == "user":
                lines.append({"type": "user", "timestamp": stamp,
                              "message": {"role": "user", "content": "..."}})
            else:
                lines.append({"type": "assistant", "timestamp": stamp,
                              "message": {"role": "assistant",
                                          "content": [{"type": "text", "text": "..."}]}})
        path.write_text("".join(json.dumps(l) + "\n" for l in lines), encoding="utf-8")

    def task(self, title: str, due_in_days: int, priority: str = "medium", area: str = "test") -> None:
        due = (datetime.now().date() + timedelta(days=due_in_days)).isoformat()
        with sqlite3.connect(self.tasks_db) as c:
            c.execute("INSERT INTO tasks (title, area, priority, status, due_date) VALUES (?,?,?,?,?)",
                      (title, area, priority, "open", due))

    def memory(self, content: str, valid_in_days: int) -> None:
        until = (datetime.now().date() + timedelta(days=valid_in_days)).isoformat()
        with sqlite3.connect(self.memory_db) as c:
            c.execute("INSERT INTO memories (content, project, type, status, valid_until) "
                      "VALUES (?,?,?,?,?)", (content, "test", "fact", "active", until))

    def run(self, prompt: str) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("KAIROS_", "CLAUDE_KIT_", "CLAUDE_SESSION"))}
        env.update({
            "HOME": str(self.home), "USERPROFILE": str(self.home),
            "CLAUDE_SESSION_ID": self.session,
            "CLAUDE_KIT_STATE_DIR": str(self.state_dir),
            "CLAUDE_TRAINING_CUTOFF": (datetime.now().date() - timedelta(days=400)).isoformat(),
        })
        payload = json.dumps({"session_id": self.session, "prompt": prompt})
        out = {}
        for hook in CHAIN:
            r = subprocess.run([sys.executable, str(HOOKS / hook)], input=payload,
                               capture_output=True, text=True, env=env, timeout=30)
            assert r.returncode == 0, (hook, r.stderr)
            assert "Traceback" not in r.stderr, (hook, r.stderr)
            out[hook] = r.stdout.strip()
        return out


@pytest.fixture
def scenario(tmp_path):
    return Scenario(tmp_path)


def ago(**kw) -> datetime:
    return utc_now() - timedelta(**kw)


def test_overnight_resumption_reorients_without_noise(scenario):
    scenario.transcript([("user", ago(hours=26)), ("assistant", ago(hours=25, minutes=55))])
    out = scenario.run("morning, where were we")
    state = out["temporal-state.py"]
    assert "(since-reply)" in state
    assert "cross-day=yes" in state
    assert "cadence=resumed-after-long-gap" in state
    assert "phase=resumed-after-overnight" in state
    routing = out["temporal-routing.py"]
    assert "memory_search-first" in routing and "flag-staleness" in routing
    assert "basis=reply" in routing
    assert out["future-state.py"] == ""
    assert out["staleness-state.py"] == ""


def test_rapid_topic_switch_trims_ceremony_only(scenario):
    events = []
    for minutes in (3, 2, 1):
        events += [("user", ago(minutes=minutes)), ("assistant", ago(minutes=minutes, seconds=-10))]
    events += [("user", ago(seconds=55)), ("assistant", ago(seconds=45))]
    scenario.transcript(events)
    out = scenario.run("different topic: review the changes from last night")
    assert "cadence=rapid-fire" in out["temporal-state.py"]
    routing = out["temporal-routing.py"]
    assert "skip=TaskCreate-overhead,preamble" in routing
    assert "basis=reply" in routing
    assert "write-longer" not in routing
    assert "suggest=" not in routing


def test_long_assistant_turn_then_quick_reply_is_not_reflective(scenario):
    scenario.transcript([
        ("user", ago(minutes=15)),
        ("assistant", ago(minutes=14)), ("assistant", ago(minutes=10)), ("assistant", ago(seconds=40)),
    ])
    out = scenario.run("looks right, go ahead with the next one please")
    state = out["temporal-state.py"]
    assert "gap=40s(since-reply)" in state
    assert "turn=15m" in state
    assert "cadence=active-collaboration" in state
    assert "reflective" not in state
    assert out["temporal-routing.py"] == ""


def test_deadline_prompt_with_overdue_and_upcoming_tasks(scenario):
    scenario.transcript([("user", ago(minutes=5)), ("assistant", ago(minutes=4))])
    scenario.task("file the report", due_in_days=-1, priority="high")
    scenario.task("renew the permit", due_in_days=3)
    line = scenario.run("what is the deadline status this week")["future-state.py"]
    assert line.startswith("[obligations] 1 overdue (1 high)")
    assert "next: 'renew the permit' in 3d" in line


def test_overdue_task_surfaces_even_without_forward_keywords(scenario):
    scenario.transcript([("user", ago(minutes=5)), ("assistant", ago(minutes=4))])
    scenario.task("file the report", due_in_days=-2)
    line = scenario.run("can you tidy the readme")["future-state.py"]
    assert "1 overdue" in line
    assert "2d overdue" in line


def test_expiring_memory_surfaces_when_the_prompt_looks_ahead(scenario):
    scenario.transcript([("user", ago(minutes=5)), ("assistant", ago(minutes=4))])
    scenario.memory("temporary access code for the site", valid_in_days=3)
    out = scenario.run("anything expiring soon that I should know about")
    assert "1 memory(ies) expiring" in out["future-state.py"]
    silent = scenario.run("tidy the readme")
    assert silent["future-state.py"] == ""


def test_ordinary_continuation_injects_nothing_beyond_the_state_line(scenario):
    scenario.transcript([("user", ago(minutes=3)), ("assistant", ago(minutes=2, seconds=50))])
    scenario.task("far away", due_in_days=30)
    out = scenario.run("ok, continue with the next file")
    assert "cadence=active-collaboration" in out["temporal-state.py"]
    assert "phase=continuing" in out["temporal-state.py"]
    assert out["temporal-routing.py"] == ""
    assert out["future-state.py"] == ""
    assert out["staleness-state.py"] == ""


def test_volatile_topic_gets_a_staleness_line(scenario):
    scenario.transcript([("user", ago(minutes=3)), ("assistant", ago(minutes=2))])
    line = scenario.run("what does the api pricing look like now")["staleness-state.py"]
    assert line.startswith("[staleness] 'api'")
    assert "risk=" in line


def test_fresh_session_says_so_and_asks_for_grounding(scenario):
    out = scenario.run("hi")
    assert "phase=session-start" in out["temporal-state.py"]
    assert "read-CLAUDE.md-first" in out["temporal-routing.py"]
