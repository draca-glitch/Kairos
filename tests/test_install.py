"""install.sh puts every hook and server in place, and each one runs from the
installed layout: the README quick start used to list four of seven hooks and
omitted the keywords module staleness-state imports, and nothing caught it."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK_FILES = sorted(p.name for p in ROOT.glob("hooks/*") if p.suffix in (".py", ".sh"))
SERVER_FILES = sorted(p.name for p in ROOT.glob("mcp/*.py"))
RUNNABLE_HOOKS = [h for h in HOOK_FILES if h not in ("temporal_lib.py", "keywords.py")]


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    dst = home / ".claude"
    result = subprocess.run([str(ROOT / "install.sh"), str(dst)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return home, dst


def test_every_hook_and_server_is_installed_and_executable(installed):
    _, dst = installed
    assert sorted(p.name for p in (dst / "hooks").iterdir()
                  if p.suffix in (".py", ".sh")) == HOOK_FILES
    assert sorted(p.name for p in (dst / "mcp").glob("*.py")) == SERVER_FILES
    for p in list((dst / "hooks").glob("*.py")) + list((dst / "hooks").glob("*.sh")) \
            + list((dst / "mcp").glob("*.py")):
        assert p.stat().st_mode & stat.S_IXUSR, p


@pytest.mark.parametrize("hook", RUNNABLE_HOOKS)
def test_each_installed_hook_runs_from_the_installed_layout(installed, hook):
    home, dst = installed
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("KAIROS_") and not k.startswith("CLAUDE_KIT_")}
    env.update({
        "HOME": str(home), "USERPROFILE": str(home),
        "CLAUDE_KIT_STATE_DIR": str(home / "state"),
        "KAIROS_HISTORY_BACKEND": "ring", "KAIROS_THREAD_ID": "t1",
    })
    payload = json.dumps({
        "session_id": "t1",
        "prompt": "what is due this week for the api deploy",
        "tool_name": "Read", "tool_input": {"file_path": "/dev/null"},
    })
    cmd = [str(dst / "hooks" / hook)] if hook.endswith(".sh") else [sys.executable, str(dst / "hooks" / hook)]
    result = subprocess.run(cmd, input=payload, capture_output=True, text=True, env=env, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr, result.stderr


def test_readme_quick_start_installs_through_the_script():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    quick_start = text.split("## Quick start", 1)[1].split("\n## ", 1)[0]
    assert "install.sh" in quick_start
    assert "cp hooks/" not in quick_start


def test_settings_template_registers_every_prompt_hook():
    template = json.loads((ROOT / "templates" / "settings.json").read_text(encoding="utf-8"))
    registered = {
        Path(h["command"]).name
        for group in template["hooks"]["UserPromptSubmit"]
        for h in group["hooks"]
    }
    for hook in ("time.sh", "temporal-state.py", "temporal-routing.py",
                 "future-state.py", "staleness-state.py"):
        assert hook in registered, hook
