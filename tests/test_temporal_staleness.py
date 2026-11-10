"""Layer 3 (mcp/temporal-staleness.py): the verdict must discriminate.

Three things saturated it: keywords matched as substrings ("api" inside
"therapist"), a topic with no recognisable domain was graded on a 60-day
half-life and came out high, and the cutoff silently defaulted when
CLAUDE_TRAINING_CUTOFF was unset. These tests pin the three fixes.
"""

import importlib.util
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "mcp" / "temporal-staleness.py"


def load(monkeypatch, cutoff: str | None):
    if cutoff is None:
        monkeypatch.delenv("CLAUDE_TRAINING_CUTOFF", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_TRAINING_CUTOFF", cutoff)
    spec = importlib.util.spec_from_file_location("temporal_staleness", SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


@pytest.fixture
def stale(monkeypatch):
    """Cutoff 300 days back: far enough that every dated domain grades high."""
    return load(monkeypatch, days_ago(300))


# --- keyword matching ---

@pytest.mark.parametrize("topic", [
    "flaw in a rapid therapist costume",     # law, api, api, cost
    "stockholm marketplace newspaper",       # stock, market, news
    "remodeling the lawn",                   # model, law
    "the proofreading drugstore",            # proof, drug
    "boiling point of water",
])
def test_keywords_do_not_fire_inside_other_words(stale, topic):
    assert stale.infer_domain_from_topic(topic) == ""


@pytest.mark.parametrize("topic,domain", [
    ("which api version should I target", "api"),
    ("public APIs for weather", "api"),
    ("latest CVE in openssl", "security"),
    ("is this vulnerable", "security"),                # stem
    ("known vulnerabilities", "security"),             # stem
    ("how is it diagnosed", "medical"),                # stem
    ("gpt-5 context window", "ai"),                    # punctuation-terminated prefix
    ("python3 asyncio", "software"),                   # trailing version number
    ("node.js streams", "software"),
    ("recommended libraries", "libraries"),            # y -> ies
    ("what is it priced at", "pricing"),               # inflection on a final e
    ("packaging formats", "libraries"),
    ("claude's tool use", "ai"),                       # possessive
    ("cryptocurrency taxes", "crypto"),
    ("stocks to watch", "stocks"),
    ("zero-day in the wild", "security"),
    ("proof of the theorem", "math"),
])
def test_keywords_match_whole_words_and_inflections(stale, topic, domain):
    assert stale.infer_domain_from_topic(topic) == domain


def test_most_volatile_match_still_wins(stale):
    assert stale.infer_domain_from_topic("price history of the api") == "pricing"


def test_inline_fallback_map_agrees_with_the_shared_one(stale):
    """The inline copy is only used standalone; it must not drift."""
    shared = list(stale._SHARED_KEYWORD_MAP)
    probes = [n if n[-1:].isalnum() else n + "4" for n, _ in shared]
    with_shared = [stale.infer_domain_from_topic(p) for p in probes]
    assert all(with_shared), "every shared keyword must match itself"
    stale._SHARED_KEYWORD_MAP = None
    assert [stale.infer_domain_from_topic(p) for p in probes] == with_shared


# --- unknown domain ---

def test_unknown_domain_caps_at_qualify(stale):
    verdict = stale.assess("boiling point of water", None)
    assert verdict["domain"] == "general-unknown"
    assert (verdict["risk"], verdict["suggestion"]) == ("medium", "qualify")
    assert "web search" not in verdict["rationale"]


def test_unrecognised_explicit_domain_caps_at_qualify(stale):
    verdict = stale.assess("sourdough hydration", "baking")
    assert (verdict["risk"], verdict["suggestion"]) == ("medium", "qualify")


def test_unknown_domain_is_low_while_the_cutoff_is_fresh(monkeypatch):
    mod = load(monkeypatch, days_ago(5))
    verdict = mod.assess("boiling point of water", None)
    assert (verdict["risk"], verdict["suggestion"]) == ("low", "proceed")


def test_known_domains_still_reach_high(stale):
    assert stale.assess("latest CVE in openssl", None)["suggestion"] == "web_search"
    assert stale.assess("anything", "news")["risk"] == "high"


def test_ageless_domains_stay_low(stale):
    assert stale.assess("proof of the theorem", None)["risk"] == "low"


def test_known_domain_within_two_half_lives_is_medium(monkeypatch):
    mod = load(monkeypatch, days_ago(120))
    verdict = mod.assess("which api version should I target", None)
    assert (verdict["half_life_days"], verdict["risk"]) == (90, "medium")


# --- cutoff provenance ---

def test_unset_cutoff_is_reported_as_assumed(monkeypatch):
    mod = load(monkeypatch, None)
    verdict = mod.assess("which api version should I target", None)
    assert verdict["cutoff_source"] == "assumed-default"
    assert verdict["cutoff_date"] == mod.DEFAULT_CUTOFF.isoformat()
    assert "assumed default" in verdict["cutoff_note"]
    assert "CLAUDE_TRAINING_CUTOFF" in verdict["cutoff_note"]


@pytest.mark.parametrize("bad", ["", "  ", "June 2026", "2026-13-40"])
def test_unreadable_cutoff_is_reported_as_assumed(monkeypatch, bad):
    mod = load(monkeypatch, bad)
    assert mod.assess("x", "news")["cutoff_source"] == "assumed-default"


def test_configured_cutoff_is_used_and_not_flagged(monkeypatch):
    mod = load(monkeypatch, days_ago(40))
    verdict = mod.assess("which api version should I target", None)
    assert verdict["cutoff_source"] == "env"
    assert verdict["days_since_cutoff"] == 40
    assert "cutoff_note" not in verdict


def test_server_process_reports_the_assumed_cutoff():
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_TRAINING_CUTOFF"}
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "temporal_staleness_audit",
                       "arguments": {"topic": "boiling point of water"}}}
    proc = subprocess.run([sys.executable, str(SERVER)], input=json.dumps(call) + "\n",
                          capture_output=True, text=True, timeout=60, env=env)
    body = json.loads(json.loads(proc.stdout.splitlines()[0])["result"]["content"][0]["text"])
    assert body["cutoff_source"] == "assumed-default"
    assert body["suggestion"] in ("proceed", "qualify")
