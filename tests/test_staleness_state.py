"""Tests for the Layer 3 staleness injection hook (hooks/staleness-state.py).

The hook reuses the temporal-staleness MCP module for the verdict; these
tests exercise the trigger regex and the render gate directly.
"""

import importlib.util
from pathlib import Path

_HOOK = Path(__file__).resolve().parent.parent / "hooks" / "staleness-state.py"
_spec = importlib.util.spec_from_file_location("staleness_state", _HOOK)
ss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ss)


def _verdict(risk, days=159, half_life=90, suggestion="qualify"):
    return {"risk": risk, "days_since_cutoff": days,
            "half_life_days": half_life, "suggestion": suggestion}


def test_render_silent_on_low_risk():
    assert ss.render("api", _verdict("low")) is None


def test_render_medium_risk_line():
    line = ss.render("api", _verdict("medium"))
    assert line == "[staleness] 'api' risk=medium (159d since cutoff, 90d half-life): qualify"


def test_render_high_risk_line():
    line = ss.render("cve", _verdict("high", days=200, half_life=30, suggestion="web_search"))
    assert "risk=high" in line and "web_search" in line


def test_render_says_when_the_cutoff_is_assumed():
    verdict = dict(_verdict("medium"), cutoff_source="assumed-default")
    assert ss.render("api", verdict) == \
        "[staleness] 'api' risk=medium (159d since assumed cutoff, 90d half-life): qualify"
    verdict["cutoff_source"] = "env"
    assert "assumed" not in ss.render("api", verdict)


def test_context_window_is_cut_at_word_boundaries():
    text = "x" * 80 + " flaw api costume " + "y" * 80
    start = text.index("api")
    window = ss.context_window(text, start, start + 3, width=5)
    # width 5 reaches into "flaw" and "costume"; neither may survive as a fragment
    assert window == "api"
    assert ss.context_window("short api text", 6, 9) == "short api text"


def test_hook_carries_the_audit_changes(monkeypatch, capsys):
    """Unknown domain caps at qualify, and an unset cutoff is labelled."""
    import io
    import json
    monkeypatch.delenv("CLAUDE_TRAINING_CUTOFF", raising=False)
    monkeypatch.delenv("KAIROS_STALENESS_INJECT", raising=False)
    monkeypatch.setenv("KAIROS_CONFIG", "/nonexistent/kairos-config.json")
    import temporal_lib
    temporal_lib.reset_config_cache()
    # "sdk" is an R7 trigger with no domain mapping; "therapist" must not map to api.
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"prompt": "which sdk does the therapist costume shop use"})))
    try:
        assert ss.main() == 0
    finally:
        temporal_lib.reset_config_cache()
    line = capsys.readouterr().out.strip()
    mod = ss.load_staleness_module()
    if mod.days_since_cutoff() < mod.UNKNOWN_HALF_LIFE / 2:
        assert line == ""           # fresh cutoff: low risk stays silent
    else:
        assert line.startswith("[staleness] 'sdk' risk=medium (")
        assert "since assumed cutoff" in line
        assert line.endswith(": qualify")


def test_trigger_regex_word_boundaries():
    assert ss.TRIGGER_RE.search("which api version is current")
    assert not ss.TRIGGER_RE.search("rapid progress on the essay")  # api inside rapid


def test_module_loads_staleness_mcp():
    mod = ss.load_staleness_module()
    assert mod is not None
    verdict = mod.assess("which api version should I target", None)
    assert verdict["risk"] in ("low", "medium", "high")
