"""Shared configuration (0.11.0): env, then ~/.config/kairos/config.json, then default.

Local preferences live in the config file so a reinstall or a fleet converge
that re-copies the hooks cannot revert them, and every harness reads the same
file. The memory DB resolves through one function everywhere.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))
import temporal_lib  # noqa: E402


def load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", {k: v for k, v in os.environ.items()
                                        if not k.startswith("KAIROS_") and k != "MNEMOS_DB"})
    os.environ["HOME"] = str(tmp_path)
    os.environ["USERPROFILE"] = str(tmp_path)
    temporal_lib.reset_config_cache()
    yield tmp_path
    temporal_lib.reset_config_cache()


def write_config(home: Path, data: dict, path: Path | None = None) -> Path:
    path = path or home / ".config" / "kairos" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    temporal_lib.reset_config_cache()
    return path


# --- setting() precedence ---

def test_default_when_nothing_is_set(home):
    assert temporal_lib.setting("future_inject", "1") == "1"
    assert temporal_lib.setting("future_inject") is None


def test_config_file_overrides_default(home):
    write_config(home, {"future_inject": False})
    assert temporal_lib.setting("future_inject", "1") == "0"


def test_env_overrides_config_file(home):
    write_config(home, {"future_inject": False})
    os.environ["KAIROS_FUTURE_INJECT"] = "1"
    assert temporal_lib.setting("future_inject", "1") == "1"


def test_kairos_config_env_selects_the_file(home):
    path = write_config(home, {"tasks_db": "/x/tasks.db"}, path=home / "elsewhere.json")
    os.environ["KAIROS_CONFIG"] = str(path)
    assert temporal_lib.setting("tasks_db") == "/x/tasks.db"


def test_corrupt_config_falls_back_to_default(home):
    path = home / ".config" / "kairos" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    temporal_lib.reset_config_cache()
    assert temporal_lib.setting("future_inject", "1") == "1"


def test_numbers_and_strings_pass_through_as_strings(home):
    write_config(home, {"future_horizon_days": 14, "history_backend": "ring"})
    assert temporal_lib.setting("future_horizon_days") == "14"
    assert temporal_lib.setting("history_backend") == "ring"


def test_setting_bool_accepts_the_usual_spellings(home):
    for raw in (True, 1, "1", "true", "yes", "on"):
        write_config(home, {"staleness_inject": raw})
        assert temporal_lib.setting_bool("staleness_inject", False) is True
    for raw in (False, 0, "0", "false", "no", "off"):
        write_config(home, {"staleness_inject": raw})
        assert temporal_lib.setting_bool("staleness_inject", True) is False


# --- memory_db_path() / tasks_db_path() ---

def test_memory_db_from_config(home):
    write_config(home, {"memory_db": "~/live.db"})
    assert temporal_lib.memory_db_path() == home / "live.db"


def test_memory_db_env_wins_over_config(home):
    write_config(home, {"memory_db": "/cfg.db"})
    os.environ["KAIROS_MEMORY_DB"] = "/env.db"
    assert temporal_lib.memory_db_path() == Path("/env.db")


def test_memory_db_honors_mnemos_own_env(home):
    os.environ["MNEMOS_DB"] = "/mnemos/live.db"
    assert temporal_lib.memory_db_path() == Path("/mnemos/live.db")


def test_memory_db_prefers_the_work_store_over_a_dot_mnemos_leftover(home):
    for p in (home / "work" / "memory.db", home / ".mnemos" / "memory.db"):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
    assert temporal_lib.memory_db_path() == home / "work" / "memory.db"


def test_memory_db_falls_back_to_dot_mnemos_when_the_work_store_is_absent(home):
    p = home / ".mnemos" / "memory.db"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"")
    assert temporal_lib.memory_db_path() == p


def test_memory_db_default_when_nothing_exists(home):
    assert temporal_lib.memory_db_path() == home / "work" / "memory.db"


def test_tasks_db_precedence(home):
    assert temporal_lib.tasks_db_path() == home / "work" / "tasks.db"
    write_config(home, {"tasks_db": "~/cfg/tasks.db"})
    assert temporal_lib.tasks_db_path() == home / "cfg" / "tasks.db"
    os.environ["KAIROS_TASKS_DB"] = "/env/tasks.db"
    assert temporal_lib.tasks_db_path() == Path("/env/tasks.db")


def test_state_dir_and_history_backend_read_the_config(home):
    write_config(home, {"state_dir": "~/kstate", "history_backend": "ring"})
    assert temporal_lib.state_dir() == home / "kstate"
    assert temporal_lib.history_backend() == "ring"
    os.environ["CLAUDE_KIT_STATE_DIR"] = "/env/state"
    assert temporal_lib.state_dir() == Path("/env/state")


# --- hooks honour the config ---

def test_future_state_disabled_by_config_and_reenabled_by_env(home):
    write_config(home, {"future_inject": False})
    fs = load(ROOT / "hooks" / "future-state.py")
    assert fs.inject_enabled() is False
    os.environ["KAIROS_FUTURE_INJECT"] = "1"
    assert fs.inject_enabled() is True


def test_future_state_horizon_from_config(home):
    write_config(home, {"future_horizon_days": 21})
    fs = load(ROOT / "hooks" / "future-state.py")
    assert fs.horizon_days() == 21


def test_staleness_state_disabled_by_config(home):
    ss = load(ROOT / "hooks" / "staleness-state.py")
    assert ss.inject_enabled() is True
    write_config(home, {"staleness_inject": False})
    assert ss.inject_enabled() is False


def test_temporal_future_mcp_resolves_both_dbs_through_the_shared_resolver(home):
    write_config(home, {"memory_db": "/cfg/mem.db", "tasks_db": "/cfg/tasks.db"})
    mod = load(ROOT / "mcp" / "temporal-future.py")
    assert mod.MEMORY_DB == Path("/cfg/mem.db")
    assert mod.TASKS_DB == Path("/cfg/tasks.db")


def test_routing_logged_only_suggests_from_config(home):
    write_config(home, {"logged_only_suggests": "a-first,b-first"})
    routing = load(ROOT / "hooks" / "temporal-routing.py")
    assert routing.logged_only_suggests() == {"a-first", "b-first"}


# --- adapters stop guessing ---

@pytest.mark.parametrize("adapter", ["codex", "grok"])
def test_adapters_no_longer_guess_the_memory_db(home, adapter):
    leftover = home / ".mnemos" / "memory.db"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(b"")
    mod = load(ROOT / "adapters" / adapter / "kairos-user-prompt.py")
    if adapter == "codex":
        mod.apply_env_defaults()
    else:
        mod.apply_env_defaults("thread-1")
    assert "KAIROS_MEMORY_DB" not in os.environ
    assert "KAIROS_TASKS_DB" not in os.environ
    assert os.environ["KAIROS_HISTORY_BACKEND"] == "ring"
