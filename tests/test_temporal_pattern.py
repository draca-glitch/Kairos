"""Layer 4 (mcp/temporal-pattern.py): the corpus is the user's prompts only.

Claude Code writes subagent kickoffs, injected context, subagent hand-backs
and compaction summaries as type "user" events, and subagent runs as whole
transcripts under <session>/subagents/. Counting them made the "user rhythm"
track agent activity. These tests pin what is and is not a prompt, what a
session is, and that an empty window says so.
"""

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "mcp" / "temporal-pattern.py"
NOW = datetime.now(timezone.utc)


def ago(**kw) -> datetime:
    return NOW - timedelta(**kw)


def event(ts: datetime, session: str = "s1", content="hello", **flags) -> dict:
    return {"type": "user", "sessionId": session,
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "message": {"role": "user", "content": content}, **flags}


def write(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


@pytest.fixture
def pattern(tmp_path, monkeypatch):
    """The server module bound to an empty projects dir under tmp_path."""
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECTS_DIR", str(projects))
    monkeypatch.setenv("KAIROS_CONFIG", str(tmp_path / "no-config.json"))
    monkeypatch.delenv("KAIROS_PATTERN_SOURCES", raising=False)
    spec = importlib.util.spec_from_file_location("temporal_pattern", SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, projects


def query(mod, metric="overview", **args):
    return mod.tool_temporal_pattern_query({"metric": metric, **args})


# --- what counts as a prompt ---

def test_flagged_events_are_not_prompts(pattern):
    mod, projects = pattern
    write(projects / "-proj" / "s1.jsonl", [
        event(ago(minutes=50)),
        event(ago(minutes=40), isMeta=True),             # injected context, hand-back
        event(ago(minutes=30), isSidechain=True),        # subagent kickoff
        event(ago(minutes=20), isCompactSummary=True),   # compaction summary
        event(ago(minutes=10)),
        "not an object",
    ])
    assert query(mod)["data"]["total_prompts"] == 2


def test_subagent_transcripts_are_skipped(pattern):
    mod, projects = pattern
    write(projects / "-proj" / "s1.jsonl", [event(ago(minutes=10))])
    write(projects / "-proj" / "s1" / "subagents" / "agent-a1.jsonl",
          [event(ago(minutes=9), session="s1"), event(ago(minutes=8), session="s1")])
    assert query(mod)["data"]["total_prompts"] == 1


def test_inline_filter_agrees_when_the_shared_library_is_absent(pattern):
    mod, _ = pattern
    mod._shared_filter = None
    assert mod._is_real_user_prompt(event(NOW)) is True
    for flag in ("isMeta", "isSidechain", "isCompactSummary"):
        assert mod._is_real_user_prompt(event(NOW, **{flag: True})) is False


# --- what counts as a session ---

def test_a_transcript_resumed_after_an_idle_gap_is_two_sessions(pattern):
    mod, projects = pattern
    write(projects / "-proj" / "s1.jsonl", [
        event(ago(hours=20, minutes=20)), event(ago(hours=20)),      # 20 min of work
        event(ago(minutes=40)), event(ago(minutes=30)),              # resumed: 10 min
    ])
    data = query(mod)["data"]
    assert data["total_sessions"] == 2
    assert data["avg_session_duration_min"] == pytest.approx(15.0)

    durations = query(mod, "session_durations")["data"]
    assert durations["sessions_with_multiple_prompts"] == 2
    assert durations["max_min"] == pytest.approx(20.0)

    gaps = query(mod, "gap_distribution")["data"]
    assert gaps["between_sessions"] == 1
    assert gaps["max_min"] == pytest.approx(19 * 60 + 20, abs=1)


def test_a_gap_at_the_threshold_does_not_split(pattern):
    mod, projects = pattern
    write(projects / "-proj" / "s1.jsonl", [
        event(ago(minutes=90)), event(ago(minutes=60)), event(ago(minutes=29)),
    ])
    sessions = mod._split_sessions(mod._build_corpus(60))
    assert [len(run) for run in sessions] == [2, 1]     # 30 min exactly stays, 31 splits


def test_sessions_never_merge_across_transcripts(pattern):
    mod, projects = pattern
    write(projects / "-proj" / "s1.jsonl", [event(ago(minutes=20), session="s1")])
    write(projects / "-proj" / "s2.jsonl", [event(ago(minutes=19), session="s2")])
    assert query(mod)["data"]["total_sessions"] == 2


# --- inputs and the empty window ---

@pytest.mark.parametrize("given,expected", [(0, 1), (-5, 1), (9999, 365), ("abc", 60), (None, 60), (30, 30)])
def test_days_back_is_clamped(pattern, given, expected):
    mod, _ = pattern
    assert query(mod, days_back=given)["days_back"] == expected


@pytest.mark.parametrize("metric", ["overview", "heatmap_hour", "heatmap_dow", "session_durations",
                                    "gap_distribution", "current_state_vs_baseline"])
def test_an_empty_window_says_no_data(pattern, metric):
    mod, _ = pattern
    data = query(mod, metric)["data"]
    assert data["total_prompts"] == 0
    assert data["note"].startswith("no data")
    assert "rare" not in json.dumps(data)


def test_single_prompt_sessions_report_no_durations_as_no_data(pattern):
    mod, projects = pattern
    write(projects / "-proj" / "s1.jsonl", [event(ago(minutes=5))])
    assert query(mod, "session_durations")["data"]["note"].startswith("no data")
    assert query(mod, "gap_distribution")["data"]["note"].startswith("no data")


def test_server_process_applies_the_same_rules(pattern):
    _, projects = pattern
    write(projects / "-proj" / "s1.jsonl", [event(ago(minutes=5)), event(ago(minutes=4), isMeta=True)])
    write(projects / "-proj" / "s1" / "subagents" / "agent-a1.jsonl", [event(ago(minutes=3))])
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "temporal_pattern_query", "arguments": {"days_back": -3}}}
    proc = subprocess.run([sys.executable, str(SERVER)], input=json.dumps(call) + "\n",
                          capture_output=True, text=True, timeout=60, env=dict(os.environ))
    body = json.loads(json.loads(proc.stdout.splitlines()[0])["result"]["content"][0]["text"])
    assert body["days_back"] == 1
    assert body["data"]["total_prompts"] == 1
