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


def test_trigger_regex_word_boundaries():
    assert ss.TRIGGER_RE.search("which api version is current")
    assert not ss.TRIGGER_RE.search("rapid progress on the essay")  # api inside rapid


def test_module_loads_staleness_mcp():
    mod = ss.load_staleness_module()
    assert mod is not None
    verdict = mod.assess("which api version should I target", None)
    assert verdict["risk"] in ("low", "medium", "high")
