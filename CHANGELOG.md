# Changelog

All notable changes to Kairos. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/spec/v2.0.0.html).

The kit is pre-1.0: minor bumps may include incompatible changes when the cost of carrying compatibility shims would outweigh the value. Patch releases (0.x.y where y > 0) are bug-fix only.

## [Unreleased]

Next probable: a controlled with-vs-without-Kairos benchmark on time-shaped reasoning tasks to upgrade the paper's "constitutive" claim from architectural assertion to measured outcome.

## [0.13.0] - 2026-09-07

Finding 6 of the external review: measure decisions, not only tool
adherence. The deterministic half is now a regression set; the behavioural
half (did the model act on the context) remains the adherence log's job.

### Added
- **Scenario regression set, `tests/test_scenarios.py`.** Each scenario
  builds a synthetic home (transcript with user and assistant timestamps,
  tasks DB, memory DB, config) and runs the real UserPromptSubmit chain
  from `hooks/` as subprocesses, asserting the injected lines and, just as
  much, their absence. Nine scenarios: overnight resumption, rapid topic
  switch, a long assistant turn followed by a quick reply, a deadline prompt
  with overdue and upcoming tasks, an overdue task with no forward keywords,
  an expiring memory, an ordinary continuation that must inject nothing
  beyond the state line, a time-volatile topic, and a fresh session.

### Fixed
- Two defects the set found on its first run. Routing labelled its basis
  only on cadence rules; R1 and R2 read the same user-side gap and now
  label it too (`reason=gap=25h55m,cross-day=yes,basis=reply`). The
  obligations gate never opened on memories alone: a prompt that looked
  ahead with an expiring memory and no tasks due produced no line. The
  widened gate now includes expiring memories, which are forward-looking
  state in exactly the same sense as upcoming tasks. 9 new tests, 230 pass.

## [0.12.0] - 2026-09-07

Findings 3 and 4 of the external review. The corpus is affected: every
`[temporal-state]` line and every tracker record before this release
measured the gap prompt-to-prompt, so a long assistant turn followed by a
quick user reply was recorded as a reflective user. Records from this
release on carry `gap_basis`, and analysis should treat the two eras
separately.

### Changed
- **Measured timing is separated from inferred human state.** The gap that
  cadence and phase classify on is now the user's own pause: measured from
  the assistant's last reply when that timestamp exists (Claude Code stamps
  every assistant transcript record, so this costs nothing there), else from
  the previous prompt. The state line names its basis, `gap=40s(since-reply)`
  or `gap=15m(since-prompt)`, shows the raw prompt-to-prompt time as `turn=`
  when the two differ in kind, and suffixes cadence with `(turn-basis)` when
  the reading could not exclude the assistant's own working time. Routing
  reasons carry `basis=reply|turn` whenever a cadence rule fired, and the
  state file and tracker records gain `gap_basis`, `reply_gap_str`,
  `turn_gap_str`. `compute_state` keeps `gap_seconds` as the classification
  gap and adds `turn_gap_seconds`, `reply_gap_seconds`, `gap_basis`.
- **R5 (reflective and long prompt, write more) requires reply basis.** On
  turn basis a "reflective" pause may be fourteen minutes of tool calls,
  which says nothing about the user. R3 (rapid-fire, trim ceremony) fires on
  either basis, since a short prompt-to-prompt time bounds the user's gap
  from above. Its comment now states what it always meant: trim preamble
  and task bookkeeping, never the substance the prompt asks for. Cadence is
  a reading of rhythm; content wins.

### Added
- **`hooks/turn-end.py`** for harnesses on the thread-ring backend. Claude
  Code needs no hook (transcripts carry the timestamps); Codex, Grok and
  anything using `adapters/` have no transcript, so until the harness runs
  this on its turn-end event their cadence stays on turn basis and is
  labelled as such. `ring_record_reply` / `ring_load_replies` store the
  timestamps alongside the prompt ring in the same file. 16 new tests,
  221 pass.

## [0.11.0] - 2026-09-07

Three of the six findings from an external review of the deployed kit (the
other three land in 0.12.0 and 0.13.0). All three are about the same thing:
a setting that lived in the wrong place.

### Added
- **Shared configuration file.** `~/.config/kairos/config.json` (or
  `KAIROS_CONFIG`) is read by every hook, MCP server and harness adapter
  through one resolver in `temporal_lib` (`setting`, `setting_bool`,
  `memory_db_path`, `tasks_db_path`, `state_dir`, `history_backend`).
  Precedence per knob: env `KAIROS_<KEY>`, then the file, then the built-in
  default. The reviewer had disabled the obligations banner by editing the
  installed `future-state.py`; the README install and the fleet converge
  both re-copy hooks from the checkout, so that preference was one upgrade
  away from silently coming back. It now lives in the file as
  `"future_inject": false` and survives any reinstall. Keys:
  `future_inject`, `staleness_inject`, `future_horizon_days`, `memory_db`,
  `tasks_db`, `state_dir`, `history_backend`, `ring_stale_seconds`,
  `pattern_sources`, `logged_only_suggests`. Template in
  `templates/kairos-config.example.json`.
- **`install.sh`.** Copies every file under `hooks/` and `mcp/` into a
  Claude home and marks them executable. The README quick start listed four
  of the seven hooks and omitted `keywords.py`, which `staleness-state.py`
  imports, so a clean install per the docs either lacked two injection
  layers or crashed one. `tests/test_install.py` runs the script into a
  temporary home and executes every installed hook from that layout, so the
  install cannot drift from the tree again. `templates/settings.json` now
  registers `staleness-state.py` and `future-state.py` too.

### Fixed
- **The memory database is resolved once, and no longer guessed per
  adapter.** Both harness adapters preferred `~/.mnemos/memory.db` whenever
  it existed. On a host whose live store is `~/work/memory.db`, the
  `~/.mnemos` file is typically an empty first-run leftover, so the Codex
  chain had been rendering its obligations line from a store with zero rows.
  The adapters no longer set DB paths; `memory_db_path()` takes
  `KAIROS_MEMORY_DB`, then config `memory_db`, then Mnemos's own
  `MNEMOS_DB`, then whichever of `~/work/memory.db` and `~/.mnemos/memory.db`
  exists, work store first. The temporal-future MCP server used a third,
  different default; it now calls the same resolver.
- Documentation said 122 tests; the suite was at 173. It is 204 after this
  release (31 new), and the count is no longer stated anywhere it can rot.


## [0.10.1] - 2026-08-20

### Fixed
- **`serverInfo` reported 1.1.0 on both 0.9.1 and 0.10.0.** Each server carried two version literals -- `SERVER_VERSION`, which `serverInfo` returns, and a second hardcoded copy in the startup banner. Both releases edited only the banner, so the version every client actually reads never moved, and 0.9.1 -- titled "version the intermediate-revision fix so deployments are identifiable" -- did not make deployments identifiable. Worse, the protocol gate's semantics changed twice in that window, so `serverInfo` could not distinguish an allowlist deployment from a range deployment, and a node that failed to pull looked identical to one that succeeded. The banner now derives from `SERVER_VERSION`, leaving exactly one version literal per file.
- **The test suite pinned the drift instead of catching it.** `test_mcp_dual_era.py` asserted `serverInfo["version"] == "1.1.0"`, so correcting the constant turned the suite red and the stale value looked load-bearing. The assertion now reads the announced version out of this CHANGELOG, which is the thing the code is supposed to match; a second test asserts each server file contains exactly one version literal, closing the duplicate-copy hole that caused the drift. Both were confirmed to fail against the bug before being trusted. 173 pass.

## [0.10.0] - 2026-08-20

### Changed
- **The protocol-version gate is a range, not an allowlist.** 0.9.0 shipped a hardcoded list of accepted revisions and 0.9.1 extended it; both were wrong, because such a list can only name the revisions its author happened to know about and refuses everything else with `-32022`. `2025-11-25` -- flagged as a known gap in 0.9.1 -- was the second working revision rejected that way. Every handshake-era revision shares one `tools/list`/`tools/call` wire format, so all three servers now accept any dated revision from `PROTOCOL_LEGACY` up to `PROTOCOL_MODERN` inclusive and serve the unnamed ones through the legacy path. Revisions newer than `PROTOCOL_MODERN` are still refused, with the known list attached so the client can downgrade; malformed and pre-legacy values are still refused. `KNOWN_VERSIONS` remains as what `server/discover` advertises -- documentation, not the gate. Server versions bump to 1.2.0. 18 new tests, 169 pass.

### Fixed
- The 0.9.1 known gap is closed: `2025-11-25` is served, and so is every other revision in the range whether or not this release has heard of it.

## [0.9.1] - 2026-08-20

### Fixed
- **The version gate no longer refuses revisions the servers can actually speak.** 0.9.0 introduced the protocol-version check with `SUPPORTED_VERSIONS = [2026-07-28, 2024-11-05]`, which made the published revisions between the two eras a hard `-32022` refusal. Before the gate existed no version was checked at all, so clients negotiating one of them worked -- the compatibility feature broke compatibility. `2025-06-18` and `2025-03-26` are now accepted: both still open with `initialize` and share the legacy `tools/list`/`tools/call` wire format, so the legacy path already serves them correctly. `server/discover` advertises every supported revision and `initialize` echoes an intermediate proposal instead of downgrading it. Server versions bump to 1.1.1. 6 new tests (3 servers x 2 revisions), 151 pass.

### Known gaps
- `2025-11-25` is a published handshake-based revision and is **not** yet accepted; it is still refused with `-32022`. Extending the allowlist one revision at a time means each future revision breaks working clients again, so the fix under consideration is to invert the rule -- serve any well-formed handshake-era version via the legacy path -- rather than to keep appending.

## [0.9.0] - 2026-08-20

### Added
- **Dual-era MCP protocol support in all three MCP servers** (temporal-pattern, temporal-staleness, temporal-future), serving spec revision 2026-07-28 alongside legacy 2024-11-05. The 2026-07-28 revision removed the initialize handshake in favor of per-request `_meta` versioning; each server now implements `server/discover` (MUST) advertising `supportedVersions`, capabilities, instructions, and cacheability; a per-request version gate returning `UnsupportedProtocolVersionError` (-32022) with the supported list as retry data; an additive result envelope (`resultType: "complete"` plus server identity in `_meta`) that legacy clients ignore; deterministic tool ordering with `ttlMs`/`cacheScope` on `tools/list`; and negotiated (not asserted) initialize, echoing a supported client proposal and answering legacy otherwise. Server versions bump to 1.1.0.
- 23 dual-era regression tests (tests/test_mcp_dual_era.py) covering discover, both eras of tools/list, legacy initialize negotiation, -32022 with retry data, and real tools/call under the modern envelope. Patch and tests contributed by the LinNuc triad node; verified against the published 2026-07-28 changelog before merge.

### Notes
- Grok adapter: current Grok CLI ignores UserPromptSubmit stdout, including
  `hookSpecificOutput.additionalContext`. Live-verified 2026-08-18. History
  and identity still work; ambient injection waits on a Grok product change.

## [0.8.0] - 2026-08-18 (Grok adapter; transcript-theft guard; harness identity)

### Added
- **Grok CLI adapter** (`adapters/grok/`): sibling of the Codex adapter. Normalizes Grok's camelCase payload (sessionId), selects the thread-ring backend, exports KAIROS_THREAD_ID for the chain, runs the injector hooks, and emits their collected output as the Claude hook JSON contract (`hookSpecificOutput.additionalContext`) because Grok treats plain UserPromptSubmit stdout as observe-only. If a Grok build does not deliver additionalContext either, that is a documented Grok product gap; the adapter still fixes history and identity. ring_record() once after the chain, same read-only-hooks contract as Codex. 11 tests.
- `mcp/temporal-pattern.py`: opt-in ring source. `KAIROS_PATTERN_SOURCES=transcripts,ring` folds thread-ring timestamps (adapter harnesses) into the activity analytics; default remains Claude transcripts only.

### Changed
- `temporal_lib.find_transcript(payload=None)`: the newest-mtime fallback now REQUIRES a Claude session identity (CLAUDE_SESSION_ID env or payload session_id). Without any identity the caller is most likely a foreign harness whose raw hooks would otherwise steal a concurrent Claude session's transcript and report its cadence as their own; session-start is the honest answer. A genuine Claude session with a rotated transcript file keeps the fallback (identity present, file missing). compute_state passes its payload through.
- `temporal_lib.resolve_thread_id`: also accepts payload `sessionId` (camelCase) and env `GROK_SESSION_ID` / `CODEX_THREAD_ID` / `CLAUDE_SESSION_ID`, in that order after the existing `session_id` / `KAIROS_THREAD_ID`.
- `hooks/time.sh`: session marker key follows the same identity chain instead of collapsing every non-Claude harness onto the shared "default" marker (date lines appeared or vanished depending on which harness fired last).
- Codex adapter: exports KAIROS_THREAD_ID for the hook chain (time.sh marker isolation), matching the Grok adapter.

## [0.7.0] - 2026-08-18 (Cross-harness history: thread-ring backend + Codex adapter)

### Added
- **Thread-ring history backend** (`hooks/temporal_lib.py`): prompt-history acquisition is now pluggable via `KAIROS_HISTORY_BACKEND`. The default (`transcript`) reads Claude Code transcripts exactly as before; `ring` reads per-thread timestamp rings under `<state dir>/thread-rings/` for harnesses that write no Claude transcripts. Thread identity comes from `payload["session_id"]` or `KAIROS_THREAD_ID`; ids are sha256-hashed before touching the filesystem; rings are capped at 20 entries, written atomically (`tmp` + `os.replace`), corrupt state degrades to session-start, and rings idle past `KAIROS_RING_STALE_SECONDS` (default 30 days) are pruned opportunistically. Hooks only read the ring: the harness adapter calls `ring_record()` exactly once per prompt AFTER the hook chain, so every hook in one prompt's chain sees identical prior state (an append-on-read design would make hook 2..n classify every prompt as very-rapid-fire). 14 tests.
- **Codex CLI adapter** (`adapters/codex/`): the previously unversioned bridge script is now a maintained artifact. It extracts prompt + thread id from Codex's hook payload, synthesizes the Claude-style payload, selects the ring backend, runs the injector chain (`time.sh`, `temporal-state`, `temporal-routing`, `future-state`, `staleness-state`), and records the prompt timestamp once. Fixes the production bug where every Codex prompt classified as `phase=session-start` because `find_transcript()` cannot see Codex threads. Machine-specific paths from the original bridge are replaced with env knobs (`KAIROS_HOOKS_DIR`, `CLAUDE_KIT_STATE_DIR`, `KAIROS_MEMORY_DB`, `KAIROS_TASKS_DB`); install and registration documented in `adapters/codex/README.md`. Grain coverage lesson for the paper: the temporal substrate is harness-agnostic, only history ACQUISITION is harness-bound, and isolating that seam is what makes the primitive portable.

- Weekday in Layer 1 injections. `temporal_lib.compute_state` now prefixes `now_str` with a deterministic English weekday abbreviation (`now=Tue_21:17_CEST(evening)`), via a fixed `DOW` tuple rather than locale-dependent `%a`. `hooks/time.sh` includes the weekday in its full-datetime form (`LC_TIME=C date '+%a %Y-%m-%d %H:%M:%S %Z'`). Motivated by a production incident (2026-08-04) where the assistant carried an off-by-one weekday label across three days of conversation; the injected timestamps contained dates but no weekday names, so the mislabeling had no ground truth to collide with. Grain coverage lesson for the paper: a temporal grain the model must derive (date to weekday) is a grain the injection layer should supply. 3 tests.

## [0.6.0] - 2026-06-10 (Layer 3 injection; session-clean adherence data)

### Added
- `hooks/staleness-state.py`: Layer 3 self-staleness delivered as **injection**, completing the migration 0.5.0 started for Layer 5. When the prompt mentions a time-volatile topic (the R7 trigger set, word-boundary matched) the hook runs the temporal-staleness audit in-process (reusing the MCP module, single source of truth) and injects one line, e.g. `[staleness] 'api' risk=high (160d since cutoff, 14d half-life): web_search`. The gate is keyword AND risk: low-risk verdicts stay silent, so fresh domains cost nothing, and keyword false positives are harmless because the line orients rather than commands. Domain inference receives a context window around the matched keyword, not the bare keyword. 5 tests.

### Changed
- `hooks/temporal-routing.py`: R7 (`temporal_staleness_audit-first`) demoted to logged-only, same treatment and same rationale as R8 in 0.5.0: measured adherence 0% fired-first / 7.7% fired-at-all. Still evaluated and written to the state file for continued measurement; suppressed from the emitted line. The logged-only reason stripping is now table-driven (`SUGGEST_REASON_PREFIX`) instead of hardcoded per advisory.
- **Session-scoped advisory attribution.** The routing state file now records the `session_id` of the prompt that produced the advisory; the PostToolUse tracker drops advisory fields (and marks `advisory_dropped: foreign-session`) when the tool call's session does not match, and `analyze-routing-adherence.py` groups turns by `(session_id, advisory_ts)`. Previously, with concurrent sessions, one session's tool calls were attributed to the other session's advisory through the shared global state file, interleaving two sessions' calls into one "turn" and corrupting first-tool adherence. Pre-fix log records without a session_id degrade to the old behavior. 3 tests.
- `hooks/future-state.py`: the `[obligations]` "next:" picker now surfaces the most actionable obligation (due today, else nearest upcoming whenever the horizon has one, else the most RECENTLY missed overdue task) instead of falling back to the most overdue. The old picker headlined the maximally-stale task forever (a 337-day-dead work order on the production box) while hiding the obligation actually nearest in time. Widening still only controls whether upcoming-only state produces a line at all. 2 tests.

## [0.5.0] - 2026-06-03 (Routing-to-injection migration)

### Added
- `hooks/future-state.py`: Layer 5 future-orientation delivered as **injection** instead of routing. Emits an ambient `[obligations]` line (overdue / due-today / next item / expiring memories) on UserPromptSubmit, reusing the temporal-future MCP's query logic (single source of truth). The gate is actual state (something overdue or due today), not keywords, so it is immune to the false-positive disease that gave R8 ~0% adherence; forward-time keywords in the prompt merely widen the gate to include upcoming-within-horizon items. 10 tests. Rationale: measured adherence showed that prescriptive "call this tool first" routing does not drive behavior even when the tool has real data behind it, whereas orienting injection (the Layer 1 mechanism) delivers the same signal without requiring compliance.

### Changed
- `analyze-routing-adherence.py`: suggest-adherence is now a three-way split (first / late / not-fired) instead of binary followed/violated. The old "fired first" bar scored a turn where the suggested tool ran second identically to one where it never ran, conflating "adhered, just not first" with "ignored" and understating real adherence. Legacy `followed`/`violated` keys are retained (followed == fired-first) so existing callers and tests are unaffected. On the current corpus this surfaces that read-CLAUDE.md-first adherence is ~26% (fired at all) versus 5% (strict first), while temporal_future_query-first remains a genuine 0/0/N. Three tests added.
- `hooks/temporal-routing.py`: R8 (`temporal_future_query-first`) demoted to logged-only. It still fires in `evaluate_rules` and is written to the routing state file so the adherence tracker keeps measuring it, but it is suppressed from the emitted `[temporal-routing]` line. R8 measured ~0% adherence and Layer 5 is now delivered by injection (`future-state.py`), so the advisory was redundant live noise. Env-overridable via `KAIROS_LOGGED_ONLY_SUGGESTS`. Three tests added.

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
