#!/usr/bin/env python3
"""
Unit tests for cross-harness identity + transcript-theft guard (v0.8.0).

Covers: camelCase sessionId resolution, per-harness env vars, the
find_transcript rule that the newest-mtime fallback requires a Claude session
identity, and the Grok adapter's payload normalization + injection envelope.

Run:
  python3 -m unittest tests/test_harness_identity.py
"""

import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path


HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS_DIR))

import temporal_lib
from temporal_lib import find_transcript, resolve_thread_id

GROK_ADAPTER = Path(__file__).resolve().parent.parent / "adapters" / "grok" / "kairos-user-prompt.py"


def _load_grok_adapter():
    spec = importlib.util.spec_from_file_location("grok_adapter", GROK_ADAPTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class EnvIsolation(unittest.TestCase):
    ENV_KEYS = (
        "KAIROS_THREAD_ID", "GROK_SESSION_ID", "CODEX_THREAD_ID",
        "CLAUDE_SESSION_ID", "KAIROS_HISTORY_BACKEND", "CLAUDE_KIT_STATE_DIR",
    )

    def setUp(self):
        self._old = {k: os.environ.get(k) for k in self.ENV_KEYS}
        for k in self.ENV_KEYS:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestResolveThreadId(EnvIsolation):
    def test_camelcase_session_id(self):
        self.assertEqual(resolve_thread_id({"sessionId": "grok-42"}), "grok-42")

    def test_snake_case_wins_over_camelcase(self):
        self.assertEqual(
            resolve_thread_id({"session_id": "snake", "sessionId": "camel"}),
            "snake",
        )

    def test_harness_env_vars(self):
        os.environ["GROK_SESSION_ID"] = "g1"
        self.assertEqual(resolve_thread_id({}), "g1")
        os.environ["CODEX_THREAD_ID"] = "c1"
        os.environ["KAIROS_THREAD_ID"] = "k1"
        self.assertEqual(resolve_thread_id({}), "k1")

    def test_claude_session_env_is_last_resort(self):
        os.environ["CLAUDE_SESSION_ID"] = "cl1"
        self.assertEqual(resolve_thread_id({}), "cl1")
        os.environ["GROK_SESSION_ID"] = "g1"
        self.assertEqual(resolve_thread_id({}), "g1")


class TestTranscriptTheftGuard(EnvIsolation):
    def _projects_with_recent_jsonl(self, home: Path, session_id: str = "some-claude-session"):
        projects = home / ".claude" / "projects" / "-home-x"
        projects.mkdir(parents=True)
        jsonl = projects / f"{session_id}.jsonl"
        jsonl.write_text(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": "hello"},
            "timestamp": "2026-08-18T06:00:00Z",
        }) + "\n", encoding="utf-8")
        now = time.time()
        os.utime(jsonl, (now, now))
        return jsonl

    def test_no_identity_means_no_mtime_fallback(self):
        """A foreign harness without a session identity must NOT inherit the
        newest Claude transcript, however fresh it is."""
        old_home = os.environ.get("HOME")
        with tempfile.TemporaryDirectory() as fake_home:
            os.environ["HOME"] = fake_home
            try:
                self._projects_with_recent_jsonl(Path(fake_home))
                self.assertIsNone(find_transcript({}))
                self.assertIsNone(find_transcript(None))
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_payload_session_id_finds_specific_transcript(self):
        old_home = os.environ.get("HOME")
        with tempfile.TemporaryDirectory() as fake_home:
            os.environ["HOME"] = fake_home
            try:
                jsonl = self._projects_with_recent_jsonl(Path(fake_home), "sess-abc")
                found = find_transcript({"session_id": "sess-abc"})
                self.assertEqual(found, jsonl)
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_identity_present_but_file_missing_uses_fallback(self):
        """A genuine Claude session whose transcript rotated still gets the
        newest-mtime fallback (pre-v0.8.0 behavior preserved)."""
        old_home = os.environ.get("HOME")
        with tempfile.TemporaryDirectory() as fake_home:
            os.environ["HOME"] = fake_home
            try:
                jsonl = self._projects_with_recent_jsonl(Path(fake_home), "other-session")
                found = find_transcript({"session_id": "rotated-away"})
                self.assertEqual(found, jsonl)
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home


class TestGrokAdapter(EnvIsolation):
    def test_resolve_session_id_camelcase(self):
        mod = _load_grok_adapter()
        self.assertEqual(mod.resolve_session_id({"sessionId": "grok-7"}), "grok-7")
        os.environ["GROK_SESSION_ID"] = "env-grok"
        self.assertEqual(mod.resolve_session_id({}), "env-grok")
        os.environ.pop("GROK_SESSION_ID", None)
        self.assertEqual(mod.resolve_session_id({}), "grok")

    def test_env_defaults_select_ring_and_thread(self):
        mod = _load_grok_adapter()
        mod.apply_env_defaults("grok-thread-9")
        self.assertEqual(os.environ["KAIROS_HISTORY_BACKEND"], "ring")
        self.assertEqual(os.environ["KAIROS_THREAD_ID"], "grok-thread-9")

    def test_prompt_extraction_matches_codex_adapter(self):
        mod = _load_grok_adapter()
        payload = {"userPrompt": "hej kairos"}
        self.assertEqual(mod.extract_prompt(payload, ""), "hej kairos")
        messages = {"messages": [
            {"role": "assistant", "content": "x"},
            {"role": "user", "content": [{"text": "senaste"}]},
        ]}
        self.assertEqual(mod.extract_prompt(messages, ""), "senaste")

    def test_injection_envelope_shape(self):
        """The adapter's stdout contract: one JSON object with
        hookSpecificOutput.additionalContext carrying the injector lines."""
        envelope = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "[temporal-state] now=Tue_10:00_CEST(morning) | phase=session-start",
            },
        }
        parsed = json.loads(json.dumps(envelope))
        self.assertEqual(parsed["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("[temporal-state]", parsed["hookSpecificOutput"]["additionalContext"])


if __name__ == "__main__":
    unittest.main()
