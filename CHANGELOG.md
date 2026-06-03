# Changelog

All notable changes to Kairos. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/spec/v2.0.0.html).

The kit is pre-1.0: minor bumps may include incompatible changes when the cost of carrying compatibility shims would outweigh the value. Patch releases (0.x.y where y > 0) are bug-fix only.

## [Unreleased]

### Changed
- `analyze-routing-adherence.py`: suggest-adherence is now a three-way split (first / late / not-fired) instead of binary followed/violated. The old "fired first" bar scored a turn where the suggested tool ran second identically to one where it never ran, conflating "adhered, just not first" with "ignored" and understating real adherence. Legacy `followed`/`violated` keys are retained (followed == fired-first) so existing callers and tests are unaffected. On the current corpus this surfaces that read-CLAUDE.md-first adherence is ~26% (fired at all) versus 5% (strict first), while temporal_future_query-first remains a genuine 0/0/N. Three tests added.

Next probable: a controlled with-vs-without-Kairos benchmark on time-shaped reasoning tasks to upgrade the paper's "constitutive" claim from architectural assertion to measured outcome.

## [0.4.0] - 2026-05-11

**Layer 5 ships.** Forward-orientation is now first-class. The kit now implements layers 1, 3, 4, 5, and 6 of the six-layer model (Layer 2 = Mnemos companion).

### Added

* `mcp/temporal-future.py`: Layer 5 future-orientation MCP. Tools `temporal_future_query(horizon_days=7)` and `temporal_obligations_for(area, horizon_days=7)` return overdue / due-today / upcoming items + expiring memories + a `highlights` list. Reads task and memory databases directly, env-configurable via `KAIROS_TASKS_DB` and `KAIROS_MEMORY_DB`. Gracefully degrades when either database is absent (returns `{available: false}` for that source).
* `tests/test_temporal_future.py`: 12 unit tests covering horizon filtering, done-status exclusion, days-until math, area filtering, expiring-memory window, both-DBs-absent fallback.
* `R8` routing rule: prompt mentions forward-time concepts (deadline, due, overdue, upcoming, schedule, tomorrow, snart, planera, this week, ...) → suggest `temporal_future_query-first`. Bilingual trigger set (English + Swedish, since user prompts mix both). Word-boundary regex, same pattern as R7.
* `R8_TRIGGER_KEYWORDS` in `hooks/keywords.py`, sibling to `R7_TRIGGER_KEYWORDS`.
* `analyze-routing-adherence.py` learns the R8 target (`mcp__temporal-future__temporal_future_query`) so adherence is measurable from day one.
* `hooks/keywords.py`: single source-of-truth for `KEYWORD_TO_DOMAIN` (staleness MCP) and `R7_TRIGGER_KEYWORDS` / `R8_TRIGGER_KEYWORDS` (routing). Eliminates the silent two-list drift between Layers 3, 5, and 6.
* `tests/test_adherence.py`: 17 unit tests covering `analyze-routing-adherence.py`. The first run surfaced a real `--since` filter bug (see Fixed).
* `tests/test_routing.py`: 14 unit tests covering the rule engine including R7 word-boundary regression guards.
* `analyze-routing-adherence.py --session-id` flag to filter records to a single session, useful for isolating concurrent runs.

### Changed

* README rule count 6 → 8 (R7 + R8 added), R5 text reworded `extended-thinking-ok` → `write-longer-reasoning-prose` (the old advisory was unactionable). Layer 5 section added with payload example + schema expectations + env vars. Status banner updated: layers shipped is now `1, 3, 4, 5, 6`.
* `templates/settings.json` hook timeouts corrected from `2` to `2000` (milliseconds). The old value caused every hook to time out immediately for adopters using the template verbatim.
* README expanded with sections on environment variables (`CLAUDE_KIT_STATE_DIR`, `KAIROS_TASKS_DB`, `CLAUDE_TRAINING_CUTOFF`, etc.), CLI utilities (`analyze-routing-adherence.py`, `tests/test_*.py`), and the time.sh-vs-custom-Layer-1 substitution note.
* `mcp/temporal-pattern.py` now reuses `is_real_user_prompt` from `hooks/temporal_lib.py` via path-injected import (with inline fallback). Removes silent duplication.
* MCP server docstrings: example registration paths changed from absolute `/root/.claude/mcp/...` to tilde-relative `~/.claude/mcp/...` so adopters can copy verbatim.
* Layer 6 docstring: now lists eight rules.

### Fixed

* R7 substring matching produced false positives: `"api"` matched inside `"rapid"`, `"new in"` matched inside `"knew in"`, etc. Trigger detection now uses a word-boundary regex (`\bapi\b`). True positives ("graphics api", "release notes for X") still fire; false positives no longer.
* `analyze-routing-adherence.py --since` filter was silently broken. `datetime.fromisoformat("2026-05-01")` yields a timezone-naive datetime, comparison against the tracker's timezone-aware log timestamps raised `TypeError`, the broad `except Exception: pass` swallowed it, and the filter no-op'd without complaint. Naive `--since` values now normalize to UTC midnight; aware values pass through unchanged.

## [0.3.0] - 2026-05-11

**Project renamed from `claude-kit` to `Kairos`.** Greek καιρός (meaning-bearing moment) names the kit's thesis directly: time-as-meaning, not time-as-clock-reading. Sibling-named with the Mnemos memory project (μνήμη).

The GitHub URL is now `github.com/draca-glitch/Kairos`; the old URL redirects forever per GitHub policy.

### Added

* `mcp/temporal-staleness.py`: Layer 3 MCP server. Tool `temporal_staleness_audit(topic, domain?)` returns risk/days-since-cutoff/half-life/rationale/suggestion. Domain-volatility table covers 30+ categories (math/history = ageless; medical/legal = 180d; tech/software = 90d; security/CVE = 30d; news/sports = 7d; crypto = 3d; weather = 1d). Domain optional, inferred from topic keywords when omitted.
* `hooks/temporal-routing.py`: Layer 6 hook. Translates temporal state to deterministic tool-routing advisories. Seven rules v0: long-gap → memory_search-first; cross-day → flag staleness; rapid-fire → skip TaskCreate-overhead/preamble; session-start → read-CLAUDE.md-first; reflective+long-prompt → write-longer-reasoning-prose; late-night-resumed → confirm-before-destructive; **R7** time-volatile-tech keywords → temporal_staleness_audit-first (integrates Layer 3).
* `hooks/temporal-routing-tracker.py`: PostToolUse companion. Logs every tool call against the advisory in force at the time, enabling offline adherence measurement.
* `hooks/temporal_lib.py`: shared classification primitives consolidated from `temporal-state.py`. Single source of truth for cadence, phase, time-of-day, gap formatting, and real-user-prompt filter.
* `hooks/keywords.py`: single source for `KEYWORD_TO_DOMAIN` (staleness MCP) and `R7_TRIGGER_KEYWORDS` (routing R7). Both consumers fall back to inline copies if unreachable.
* `analyze-routing-adherence.py`: falsifiability analyzer. Joins tracker JSONL by `advisory_ts` and reports skip-adherence and suggest-first-adherence per advisory class. Supports `--since`, `--json`, `--log`.
* `tests/test_temporal_lib.py`: 26 table-driven unit tests covering `classify_cadence`, `classify_phase`, `tod_bucket`, `humanize_gap`, payload parsing, real-user-prompt filter.

### Changed

* Staleness MCP keyword inference changed from first-match-wins to **shortest-half-life-wins** scoring. Previously `"bitcoin price today"` resolved to `pricing` (14d); now resolves to `crypto` (3d). `"pricing"` and `"cost"` added as explicit keywords (`"price"` is not a substring of `"pricing"`).
* `temporal_lib.collect_user_prompt_timestamps` now sorts timestamps before slicing; previously assumed file order equaled chronological order.
* `temporal-routing-tracker` records `session_id` (from payload or `CLAUDE_SESSION_ID` env) so concurrent sessions can be disentangled in offline analysis.
* `find_transcript` idle-cutoff extended from 5 minutes to 4 hours (`CLAUDE_KIT_TRANSCRIPT_MAX_IDLE_SECONDS` override). Old cutoff silently degraded the pipeline after any ordinary work pause.
* R5 reformulated from `extended-thinking-ok` (unactionable, extended thinking is a request-level setting) to `write-longer-reasoning-prose` (handlingsbar).
* State file and log file paths moved from hardcoded `/root/work/` to env-configurable `~/.claude/state/` (`CLAUDE_KIT_STATE_DIR` override).
* `mcp/temporal-pattern.py` now imports `is_real_user_prompt` from `hooks/temporal_lib.py` via path injection, with inline fallback for standalone distribution. Removes silent code duplication.
* README: rule count corrected (6 → 7), R5 advisory text updated, env vars and CLI utilities documented, time.sh-vs-custom Layer-1 substitution clarified.

### Fixed

* `templates/settings.json` hook timeouts changed from `2` to `2000` (milliseconds). The old value caused every hook to time out immediately for adopters using the template verbatim.

### Infrastructure

* Size-based log rotation in tracker. Defaults: 10 MB rollover, 3 archives retained. Override via `CLAUDE_KIT_LOG_ROTATE_BYTES` / `CLAUDE_KIT_LOG_KEEP_ROTATIONS`.

## [0.2.0] - earlier

* `hooks/time.sh` v2: smart date emission. Full timestamp on first prompt of a session, date-on-change thereafter; reduces token overhead on long sessions where every prompt previously got a redundant date prefix.

## [0.1.0] - baseline

* `hooks/time.sh` v1: full timestamp on every user prompt.
* `hooks/statusline.sh`: Linux status line with host, load, memory, disk, uptime.
* `hooks/statusline-windows.sh` + `hooks/statusline.ps1`: Windows-native status line variant for Git Bash / WSL users. 30s cache to absorb PowerShell startup latency.
