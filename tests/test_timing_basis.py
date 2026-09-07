"""0.12.0: measured timing is separated from inferred human state.

The gap used to be prompt-to-prompt, which credits the assistant's tool time
to the user's cadence: fourteen minutes of tool calls and a forty-second
reply read as "reflective". Cadence and phase now classify on the user's own
gap (since the assistant's last reply) whenever that timestamp exists, and
every consumer labels which basis it used.
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
sys.path.insert(0, str(ROOT / "hooks"))
import temporal_lib  # noqa: E402
from temporal_lib import user_gaps  # noqa: E402


def load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


NOW = datetime(2026, 9, 7, 8, 0, 0, tzinfo=timezone.utc)


def ago(**kw) -> datetime:
    return NOW - timedelta(**kw)


@pytest.fixture
def home(tmp_path):
    saved = dict(os.environ)
    for k in list(os.environ):
        if k.startswith("KAIROS_") or k.startswith("CLAUDE_KIT_") or k == "CLAUDE_SESSION_ID":
            del os.environ[k]
    os.environ["HOME"] = str(tmp_path)
    os.environ["USERPROFILE"] = str(tmp_path)
    temporal_lib.reset_config_cache()
    yield tmp_path
    os.environ.clear()
    os.environ.update(saved)
    temporal_lib.reset_config_cache()


# --- user_gaps(): the pure classification input ---

def test_current_gap_is_since_reply_when_the_assistant_answered_after_the_last_prompt():
    prompts = [ago(minutes=30), ago(minutes=15)]
    replies = [ago(minutes=29), ago(seconds=40)]
    gaps, basis, turn_gap = user_gaps(prompts, replies, NOW)
    assert basis == "reply"
    assert gaps[0] == pytest.approx(40)
    assert turn_gap == pytest.approx(15 * 60)
    # the earlier prompt's gap is measured from the reply before it, not the prompt
    assert gaps[1] == pytest.approx(14 * 60)


def test_no_replies_falls_back_to_prompt_to_prompt_with_turn_basis():
    prompts = [ago(minutes=30), ago(minutes=15)]
    gaps, basis, turn_gap = user_gaps(prompts, [], NOW)
    assert basis == "turn"
    assert gaps == pytest.approx([15 * 60, 15 * 60])
    assert turn_gap == pytest.approx(15 * 60)


def test_an_interval_without_a_reply_falls_back_for_that_interval_only():
    prompts = [ago(minutes=30), ago(minutes=20), ago(minutes=10)]
    replies = [ago(minutes=29), ago(seconds=30)]  # nothing between prompt 2 and 3
    gaps, basis, _ = user_gaps(prompts, replies, NOW)
    assert basis == "reply"
    assert gaps[0] == pytest.approx(30)
    assert gaps[1] == pytest.approx(10 * 60)   # prompt3 - prompt2, no reply between
    assert gaps[2] == pytest.approx(9 * 60)    # prompt2 - reply after prompt1


def test_mid_turn_message_uses_turn_basis_for_the_current_gap():
    # the user sent again before the assistant produced anything
    prompts = [ago(minutes=5), ago(seconds=20)]
    replies = [ago(minutes=4)]
    gaps, basis, _ = user_gaps(prompts, replies, NOW)
    assert basis == "turn"
    assert gaps[0] == pytest.approx(20)


def test_empty_history_is_session_start():
    assert user_gaps([], [], NOW) == ([], None, None)


# --- transcript backend: assistant timestamps come for free ---

def write_transcript(home: Path, session_id: str, events: list[tuple[str, datetime]]) -> Path:
    path = home / ".claude" / "projects" / "-root" / f"{session_id}.jsonl"
    path.parent.mkdir(parents=True)
    lines = []
    for kind, ts in events:
        stamp = ts.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        if kind == "user":
            lines.append({"type": "user", "timestamp": stamp,
                          "message": {"role": "user", "content": "hello"}})
        elif kind == "tool_result":
            lines.append({"type": "user", "timestamp": stamp,
                          "message": {"role": "user",
                                      "content": [{"type": "tool_result", "content": "x"}]}})
        else:
            lines.append({"type": "assistant", "timestamp": stamp,
                          "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}})
    path.write_text("\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8")
    return path


def test_collect_turn_timestamps_reads_prompts_and_assistant_events(home):
    path = write_transcript(home, "s1", [
        ("user", ago(minutes=30)), ("assistant", ago(minutes=29)),
        ("tool_result", ago(minutes=28)), ("assistant", ago(minutes=27)),
        ("user", ago(minutes=15)), ("assistant", ago(seconds=40)),
    ])
    prompts, replies = temporal_lib.collect_turn_timestamps(path)
    assert [p.replace(tzinfo=None) for p in prompts] == [
        ago(minutes=30).replace(tzinfo=None), ago(minutes=15).replace(tzinfo=None)]
    assert len(replies) == 3
    assert replies[-1].replace(tzinfo=None) == ago(seconds=40).replace(tzinfo=None)


def test_compute_state_classifies_on_the_users_gap_not_the_assistants(home, monkeypatch):
    write_transcript(home, "s2", [
        ("user", datetime.now(timezone.utc) - timedelta(minutes=15)),
        ("assistant", datetime.now(timezone.utc) - timedelta(seconds=40)),
    ])
    os.environ["CLAUDE_SESSION_ID"] = "s2"
    state = temporal_lib.compute_state({"session_id": "s2", "prompt": "x"})
    assert state["gap_basis"] == "reply"
    assert 30 <= state["gap_seconds"] <= 60
    assert 14 * 60 <= state["turn_gap_seconds"] <= 16 * 60
    assert state["cadence"] == "active-collaboration"
    assert state["gap_str"] == state["reply_gap_str"]


def test_compute_state_without_assistant_events_reports_turn_basis(home):
    write_transcript(home, "s3", [("user", datetime.now(timezone.utc) - timedelta(minutes=15))])
    os.environ["CLAUDE_SESSION_ID"] = "s3"
    state = temporal_lib.compute_state({"session_id": "s3", "prompt": "x"})
    assert state["gap_basis"] == "turn"
    assert state["reply_gap_seconds"] is None
    assert state["cadence"] == "reflective-pace"


# --- ring backend: a turn-end hook supplies the reply timestamps ---

def test_ring_records_replies_and_compute_state_uses_them(home):
    os.environ["KAIROS_HISTORY_BACKEND"] = "ring"
    temporal_lib.ring_record("t1", datetime.now(timezone.utc) - timedelta(minutes=15))
    state = temporal_lib.compute_state({"session_id": "t1", "prompt": "x"})
    assert state["gap_basis"] == "turn"
    temporal_lib.ring_record_reply("t1", datetime.now(timezone.utc) - timedelta(seconds=40))
    assert len(temporal_lib.ring_load_replies("t1")) == 1
    state = temporal_lib.compute_state({"session_id": "t1", "prompt": "x"})
    assert state["gap_basis"] == "reply"
    assert state["cadence"] == "active-collaboration"
    # the prompt ring is untouched by reply recording
    assert len(temporal_lib.ring_load("t1")) == 1


def test_turn_end_hook_records_a_reply_into_the_ring(home):
    env = {**os.environ, "KAIROS_HISTORY_BACKEND": "ring", "KAIROS_THREAD_ID": "t9"}
    result = subprocess.run([sys.executable, str(ROOT / "hooks" / "turn-end.py")],
                            input=json.dumps({"session_id": "t9"}), capture_output=True,
                            text=True, env=env, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert len(temporal_lib.ring_load_replies("t9")) == 1


def test_turn_end_hook_is_a_no_op_on_the_transcript_backend(home):
    result = subprocess.run([sys.executable, str(ROOT / "hooks" / "turn-end.py")],
                            input=json.dumps({"session_id": "t10"}), capture_output=True,
                            text=True, env=dict(os.environ), timeout=20)
    assert result.returncode == 0
    assert temporal_lib.ring_load_replies("t10") == []


# --- the state line labels both measurements ---

def base_state(**over):
    state = {
        "transcript_available": True, "prompts_count": 3,
        "now_str": "Mon_08:00_CEST", "tod": "early-morning",
        "gap_seconds": 40, "gap_str": "40s", "gap_basis": "reply",
        "reply_gap_seconds": 40, "reply_gap_str": "40s",
        "turn_gap_seconds": 900, "turn_gap_str": "15m",
        "cross_day": False, "cadence": "active-collaboration", "phase": "continuing",
        "prompt_text": "x",
    }
    state.update(over)
    return state


def test_state_line_shows_since_reply_and_since_prompt_separately():
    ts = load(ROOT / "hooks" / "temporal-state.py")
    line = ts.render_line(base_state())
    assert "gap=40s(since-reply)" in line
    assert "turn=15m" in line
    assert "cadence=active-collaboration |" in line


def test_state_line_flags_turn_basis_cadence_as_unverified():
    ts = load(ROOT / "hooks" / "temporal-state.py")
    line = ts.render_line(base_state(gap_basis="turn", gap_seconds=900, gap_str="15m",
                                     reply_gap_seconds=None, reply_gap_str=None,
                                     cadence="reflective-pace"))
    assert "gap=15m(since-prompt)" in line
    assert "turn=" not in line
    assert "cadence=reflective-pace(turn-basis)" in line


# --- routing: cadence rules name their basis; R5 needs a real user gap ---

def test_r5_does_not_fire_on_turn_basis():
    routing = load(ROOT / "hooks" / "temporal-routing.py")
    long_prompt = "x" * 300
    on_reply = base_state(cadence="reflective-pace", gap_basis="reply", prompt_text=long_prompt)
    on_turn = base_state(cadence="reflective-pace", gap_basis="turn", prompt_text=long_prompt)
    s1, _, r1 = routing.evaluate_rules(on_reply)
    s2, _, r2 = routing.evaluate_rules(on_turn)
    assert "write-longer-reasoning-prose" in s1
    assert "write-longer-reasoning-prose" not in s2
    assert "basis=reply" in r1


def test_r3_fires_on_either_basis_and_names_it():
    routing = load(ROOT / "hooks" / "temporal-routing.py")
    _, skips, reasons = routing.evaluate_rules(base_state(cadence="rapid-fire", gap_basis="turn"))
    assert "preamble" in skips
    assert "basis=turn" in reasons


def test_state_file_and_tracker_record_the_basis(home, tmp_path):
    os.environ["CLAUDE_KIT_STATE_DIR"] = str(tmp_path / "state")
    routing = load(ROOT / "hooks" / "temporal-routing.py")
    state = base_state()
    state["now_local"] = datetime.now(timezone.utc).astimezone()
    routing.write_state_file(state, ["memory_search-first"], [], ["gap=40s"], "sess")
    written = json.loads(routing.STATE_FILE.read_text())
    assert written["gap_basis"] == "reply"
    assert written["reply_gap_str"] == "40s"
    assert written["turn_gap_str"] == "15m"
    env = {**os.environ}
    subprocess.run([sys.executable, str(ROOT / "hooks" / "temporal-routing-tracker.py")],
                   input=json.dumps({"session_id": "sess", "tool_name": "Read"}),
                   capture_output=True, text=True, env=env, timeout=20, check=True)
    log = (tmp_path / "state" / "temporal-routing-log.jsonl").read_text().strip().splitlines()
    record = json.loads(log[-1])
    assert record["gap_basis"] == "reply"
    assert record["turn_gap_str"] == "15m"
