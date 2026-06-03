# Kairos

> *kairos* (καιρός): the meaning-bearing moment, as distinct from *chronos* (Χρόνος), measured time. This kit is about the former: not "what does the clock say" but "what does the time *mean* for this turn".

> **Status: work in progress.** Kairos is the public artifact accompanying the **Wedlund Temporal Theorem**, a research project by Mikael Wedlund on temporal cognition as a constitutive primitive of artificial intelligence. The kit is the substrate the theory is being tested against, not the final claim. Layers 1, 3, 4, 5, and 6 ship today (v0.5.0); Layer 2 is provided by the companion [Mnemos](https://github.com/draca-glitch/mnemos) memory project; the paper is unpublished. API is pre-1.0 and may change between minor versions.

Small things that make Claude Code feel less stateless:

1. **`hooks/time.sh`**: injects current server time on every user prompt so Claude has temporal cohesion across your messages. Without it, Claude sees all your messages as "now" and can't tell whether you replied in 10 seconds or 10 hours.
2. **`hooks/temporal-state.py`**: sibling of `time.sh`. Where time.sh gives the raw timestamp, this one computes the *shape* of time and prepends it as a single-line summary: gap-since-last, cross-day status, time-of-day bucket, input-cadence (rapid-fire vs reflective vs resumed-after-gap), and session-phase (continuing vs interruption-pivot vs session-start). Lets Claude arrive at the prompt with computed temporal context already grounded instead of having to derive it each turn.
3. **`hooks/temporal-routing.py`**: Layer 6. Translates the temporal state into deterministic tool-routing advisories (`suggest=memory_search-first`, `skip=TaskCreate-overhead`, etc.) so the temporal signal isn't only informational but procedural. Eight rules v0: long-gap → memory-first, cross-day → staleness flag, rapid-fire → skip overhead, session-start → read CLAUDE.md, reflective + long prompt → write-longer-reasoning-prose, late-night-resumed → confirm-before-destructive, tech-keyword prompt → temporal_staleness_audit-first (R7, integrates Layer 3), forward-time prompt → temporal_future_query-first (R8, integrates Layer 5). Silent when no rule fires.
4. **`hooks/temporal-routing-tracker.py`**: PostToolUse companion to routing. Logs every tool call alongside the advisory in force at the time so adherence can be measured offline (falsifiability).
5. **`mcp/temporal-pattern.py`**: MCP server exposing `temporal_pattern_query` tool. Where `time.sh` and `temporal-state.py` tell Claude about *this moment*, this one lets Claude query the user's *baseline pattern* across all recorded sessions: hour-of-day activity heatmap, session durations, between-session gaps, and a current-state-vs-baseline comparison. Lets Claude calibrate pacing/tone against your real rhythm, not heuristics.
6. **`mcp/temporal-staleness.py`**: MCP server exposing `temporal_staleness_audit` tool. Given a topic + optional domain, returns a stale-risk assessment (`low/medium/high`) based on time-since-training-cutoff and domain-volatility table (tech: 90d half-life, news: 7d, security/CVE: 30d, etc.). Tells Claude when to web-search vs proceed vs qualify.
7. **`mcp/temporal-future.py`**: Layer 5. MCP server exposing `temporal_future_query` and `temporal_obligations_for` tools. Reads the agent's task database and Mnemos memory store and returns overdue / due-today / upcoming items plus expiring memories within a horizon (default 7 days), with a `highlights` list of one-liners the model should pay attention to. Lets Claude anticipate what's coming, not just describe what's now.
That's the whole kit. Intentionally small, deliberately layered: each piece names *which layer of temporal cognition* it provides (1: present-moment, 3: self-staleness, 4: other-temporal-modeling, 5: future-orientation, 6: meta-tool-routing) in the six-layer model.

## Temporal pattern MCP

```
$ python3 mcp/temporal-pattern.py current_state_vs_baseline
{
  "data": {
    "now": "2026-05-11 16:09 CEST",
    "current_hour": 16,
    "current_dow": "Mon",
    "activity_at_this_hour": {
      "share_of_total": 0.034,
      "ratio_vs_uniform": 0.82,
      "interpretation": "below-typical"
    },
    "activity_on_this_dow": {
      "share_of_total": 0.19,
      "ratio_vs_uniform": 1.33,
      "interpretation": "typical-or-busier"
    },
    "gap_since_last_prompt_min": 1.8,
    "total_prompts_in_window": 3012
  }
}
```

Six metrics:
- `overview`: summary
- `heatmap_hour`: hour-of-day activity buckets
- `heatmap_dow`: day-of-week activity buckets
- `session_durations`: minute distribution (min/p25/median/p75/p90/max)
- `gap_distribution`: between-session gap distribution
- `current_state_vs_baseline`: now vs historical for this hour/dow

Pure stdlib. Registered as `temporal-pattern` MCP server in `~/.claude.json`. Activates per-session.

## Temporal state line

```
[temporal-state] gap=11h17m | cross-day=yes | now=02:02_CEST(late-night) | cadence=resumed-after-long-gap | phase=interruption-pivot
```

Parses the last 20 real user prompts from the current session JSONL (filtering out tool-results and task-notifications) and derives:

- **gap**: seconds/minutes/hours since the previous user message
- **cross-day**: did the local date change since the last message
- **now**: current local time + bucket (`late-night` / `early-morning` / `morning` / `midday` / `afternoon` / `evening` / `night`)
- **cadence**: `very-rapid-fire` / `rapid-fire` / `active-collaboration` / `reflective-pace` / `spaced-work` / `resumed-after-break` / `resumed-after-long-gap` / `session-start`
- **phase**: `session-start` / `continuing` / `resumed-after-pause` / `resumed-after-overnight` / `interruption-pivot`

Pure stdlib Python, no extra dependencies. Same task-notification filter as `time.sh`, so background-task completions don't trigger spurious refreshes.

Shared primitives live in `hooks/temporal_lib.py` (transcript discovery, gap classification, cadence/phase logic) so siblings like `temporal-routing.py` can reuse them without duplication.

## Temporal routing (Layer 6)

```
[temporal-routing] suggest=memory_search-first,read-CLAUDE.md-first | skip=TaskCreate-overhead | reason=gap=42m,phase=session-start
```

Runs as a second `UserPromptSubmit` hook after `temporal-state.py`. Where the state hook *describes* time, the routing hook *recommends* procedural adjustments: which tool to call first, what to skip, what posture to take. Output is single-line and silent when no rule fires, so nothing gets nudged when nothing matters.

Eight deterministic rules v0:

| Trigger | Advice |
|---------|--------|
| gap ≥ 30 min | suggest memory_search-first |
| cross-day=yes AND gap ≥ 4h | suggest memory_search-first; flag staleness |
| cadence ∈ {rapid-fire, very-rapid-fire} | skip TaskCreate-overhead, skip preamble |
| phase=session-start | suggest read-CLAUDE.md-first |
| cadence=reflective-pace AND prompt > 200 chars | suggest write-longer-reasoning-prose |
| time-of-day=late-night AND resumed-after-* cadence | suggest confirm-before-destructive |
| prompt mentions time-volatile-tech keyword | suggest temporal_staleness_audit-first (R7, Layer 3 integration) |
| prompt mentions forward-time concept | suggest temporal_future_query-first (R8, Layer 5 integration) |

Companion `hooks/temporal-routing-tracker.py` is a `PostToolUse` hook that records every tool call alongside the advisory in force at the time (in `$CLAUDE_KIT_STATE_DIR/temporal-routing-log.jsonl`), so adherence statistics can be computed offline. This is the falsifiability layer: with vs without temporal-aware routing should produce measurably different tool-sequence distributions. Run `./analyze-routing-adherence.py` against the log to compute per-advisory adherence rates.

## Staleness audit (Layer 3)

```
$ # via MCP, args = {"topic": "latest Python release"}
{
  "topic": "latest Python release",
  "domain": "software",
  "domain_source": "inferred-or-default",
  "days_since_cutoff": 130,
  "cutoff_date": "2026-01-01",
  "half_life_days": 90,
  "risk": "medium",
  "rationale": "130d since training cutoff vs 90d domain half-life (ratio 1.44), qualify answer with 'as of training cutoff' and note possible drift.",
  "suggestion": "qualify"
}
```

MCP server exposing `temporal_staleness_audit(topic, domain?)`. Returns a risk assessment based on time-since-training-cutoff against a domain-volatility table:

| Domain category | Half-life |
|-----------------|-----------|
| math, history, classics, philosophy | ageless |
| medical, legal, regulation | 180 d |
| programming, tech, software, libs, api | 90–120 d |
| ml, llm | 60–90 d |
| security, CVE, exploits | 30 d |
| pricing, markets | 14 d |
| news, politics, sports | 7 d |
| crypto, weather | 1–3 d |

Suggestions: `proceed` (low risk), `qualify` (medium), `web_search` (high). Domain is optional, if omitted, the tool infers from keywords in the topic. Training cutoff is `2026-01-01` by default; override via `CLAUDE_TRAINING_CUTOFF` env var.

## Future orientation (Layer 5)

```
$ # via MCP, args = {"horizon_days": 7}
{
  "now": "2026-05-11T22:14:45 CEST",
  "horizon_days": 7,
  "tasks": {
    "counts": {"overdue": 23, "due_today": 0, "upcoming_in_horizon": 2},
    "overdue":  [{"id": 91, "title": "WO 1235527: ...", "area": "iss-seb-pdc2", "due_date": "2025-06-02", "days_until": -343, ...}],
    "upcoming": [{"id": 64, "title": "Reservkraftsprov PDC1 – Maj", "due_date": "2026-05-17", "days_until": 6, ...}]
  },
  "expiring_memories": {"available": true, "count": 0, "expiring": []},
  "highlights": [
    "23 overdue task(s) (4 high-priority)",
    "next: 'Reservkraftsprov PDC1 – Maj' in 6d (iss-seb-pdc1)"
  ]
}
```

MCP server exposing `temporal_future_query(horizon_days=7)` and `temporal_obligations_for(area, horizon_days=7)`. Reads task and memory databases directly (paths via `KAIROS_TASKS_DB` and `KAIROS_MEMORY_DB`, defaults `~/work/tasks.db` and `~/work/memory.db`). If a database does not exist on disk, that source reports `{available: false}` and the rest of the query still returns; adopters without a tasks system still get expiring-memory queries, and adopters without memory still get task queries.

Schema expectations:

| DB | Table | Required fields |
|---|---|---|
| tasks | `tasks` | `id`, `title`, `area`, `priority` (`high`/`medium`/`low`), `status` (`open`/`done`/`cancelled`), `due_date` (ISO date or NULL) |
| memory | `memories` | `id`, `content`, `status`, `valid_until` (ISO date or NULL), Mnemos schema |

The `highlights` list is the model's quick-attention layer: one-liners like `"3 task(s) due TODAY"`, `"23 overdue (4 high-priority)"`, `"next: <title> in 6d (area)"`, `"M memory(ies) expiring in window"`. Designed to fit in a thinking budget so the model can absorb forward-state without parsing the structured payload.

## Quick start

```bash
# 1. Copy the hooks
mkdir -p ~/.claude/hooks ~/.claude/mcp
cp hooks/time.sh ~/.claude/hooks/
cp hooks/temporal_lib.py hooks/temporal-state.py hooks/temporal-routing.py hooks/temporal-routing-tracker.py ~/.claude/hooks/
cp mcp/temporal-pattern.py mcp/temporal-staleness.py mcp/temporal-future.py ~/.claude/mcp/
chmod +x ~/.claude/hooks/*.sh ~/.claude/hooks/*.py ~/.claude/mcp/*.py

# 2. Merge the UserPromptSubmit and PostToolUse entries from
#    templates/settings.json into your ~/.claude/settings.json. Register the
#    temporal-pattern, temporal-staleness, and temporal-future MCP
#    servers in ~/.claude.json.
#    Don't overwrite, you probably have other hooks, permissions, and MCPs.

# 3. Restart Claude Code or open /hooks once so the watcher picks it up.
```

Verify live: next message to Claude should arrive with something like `2026-04-17 23:55:18 CEST` prepended as a system reminder.

## CLI utilities

### `analyze-routing-adherence.py`

Reads the tracker's JSONL log and reports per-advisory adherence: when `skip=X` was in force, did the model avoid calling X? When `suggest=Y-first` was in force, did Y fire as the first tool call?

```bash
./analyze-routing-adherence.py                     # default log location
./analyze-routing-adherence.py --since 2026-05-01  # window
./analyze-routing-adherence.py --json              # machine-readable
```

Read-only. Closes the falsifiability claim: with this script, "Layer 6 shapes behavior" becomes a number, not a hypothesis.

### `tests/test_temporal_lib.py`

Table-driven unit tests over the classification primitives (cadence, phase, time-of-day, gap humanizer, prompt parsing). Hardens Layer 1+2 against regressions.

```bash
python3 -m unittest tests.test_temporal_lib
```

## Environment variables

| Variable | Default | What |
|---|---|---|
| `CLAUDE_KIT_STATE_DIR` | `~/.claude/state/` | Where routing state file and tracker log live |
| `CLAUDE_KIT_TRANSCRIPT_MAX_IDLE_SECONDS` | `14400` (4h) | How stale a transcript can be before fallback path gives up |
| `CLAUDE_KIT_LOG_ROTATE_BYTES` | `10485760` (10 MB) | When tracker log rotates |
| `CLAUDE_KIT_LOG_KEEP_ROTATIONS` | `3` | How many rotated logs to keep before deletion |
| `CLAUDE_TRAINING_CUTOFF` | `2026-01-01` | Date staleness MCP measures elapsed days against |
| `KAIROS_TASKS_DB` | `~/work/tasks.db` | Task database read by Layer 5 (temporal-future MCP) |
| `KAIROS_MEMORY_DB` | `~/work/memory.db` | Memory database read by Layer 5 for expiring memories |

## time.sh vs. custom Layer-1 sources

The kit ships `hooks/time.sh` as the default Layer 1 (present-moment grounding) hook: emits a full timestamp on first prompt of a session, then date-on-change thereafter (deduplicated, low-token). If your environment already provides a per-prompt timestamp via a different hook (for instance, a sibling script that prepends `HH:MM:SS` to every prompt), substitute it in `settings.json` instead of `time.sh`. All downstream temporal hooks (`temporal-state.py`, `temporal-routing.py`) only need an accurate session-aware clock somewhere in the chain; they don't depend on time.sh specifically. Just don't run two timestamp emitters in parallel.

## Why

### Time hook

Claude, by default, **lacks temporal cohesion**. A new message from you looks identical whether you wrote it 10 seconds or 10 hours after the previous one. From Claude's side, there's no "between", each turn is a fresh forward pass. The gap doesn't exist.

But here's the thing: the model does not know it doesn't know. When the conversation needs a time-shaped input, "it's been a while," "good morning," "maybe call it a night", that slot in the reasoning has to be filled with something. Without a real timestamp, the model fills it by **confabulation**. You've seen the outputs:

- "Good morning!" at midnight
- "You must be tired" after one minute of inactivity
- "Go to bed, it's late" at 8pm
- "It's been a while since your last message" 30 seconds in
- "Take your time" on a message you've been typing for 2 hours

Those aren't cute glitches. Those are the model silently hallucinating a temporal premise and then reasoning downstream from it. The conclusions that follow inherit the bad premise. The hook doesn't *add* temporal cognition to Claude, Claude was already doing time-inference, just blindly. The hook replaces **confabulation with grounding**. Same reasoning loop, correct input.

This hook fixes it by prepending the current server time to every user prompt as a system reminder. With a timestamp on every turn, Claude can compute the delta and adjust:

- "You just wrote 30 seconds ago, stay terse"
- "You've been away 6 hours, catch me up"
- "It's late evening, you're probably wrapping up, tighten the thread"

**Yes, it costs tokens.** About 20 per prompt (the timestamp string plus a short system-reminder framing). Over a busy day that's maybe 2-3k tokens of overhead. In Opus 4.7 pricing, a few cents. Not nothing, but trivial compared to the quality gain.

**Is it worth it?** Yes. The difference between "Claude responds to what I typed" and "Claude responds to what I typed knowing I've been away at dinner and might need context re-loaded" is surprisingly large. It makes the conversation feel continuous instead of a series of cold starts. For anything that looks like an ongoing collaboration (vs one-shot tasks), the token cost is paid back in fewer misfires per turn.

### Pair it with a memory system

The time hook gets *much* better when Claude also has persistent memory across sessions. Timestamps become anchors the memory can reference: *"last Tuesday you stored X, and now it's Friday, update?"* Without memory, the time signal is just a within-session cue. With memory, it becomes a spine for continuity across weeks. If you're running [Mnemos](https://github.com/draca-glitch/mnemos) or similar, the combination is a real unlock, stored memories carry accurate dates, recall gets temporally coherent, and Claude can actually reason about "how long has it been."

### What Claude Code already does (and why it's not enough)

Claude Code does inject the current **date** at session start, you can see it in the system context (`Today's date is YYYY-MM-DD`). Two problems:

1. **It's the date, not the time.** No hour, no minute. The model knows it's 2026-04-18 but not whether it's 09:00 or 22:00. So even within a single day it can't reason about morning vs evening, can't compute "5 minutes ago" vs "5 hours ago," can't correlate with timestamps in logs / cron / anything operational. Date alone is the wrong granularity for the kind of work people actually do in long sessions.
2. **It's frozen at session start.** With tmux that's the default for serious work, sessions run overnight, across weekends, sometimes for days. The session-start date is a one-time stamp, not a live clock. Run a session into tomorrow and Claude still thinks it's yesterday.

The hook fixes both. Every prompt brings a fresh, full timestamp (`YYYY-MM-DD HH:MM:SS TZ`), so Claude always knows the actual present moment, date, time, and timezone, not just what date the session happened to start on.

### The missing reference point

Almost every memory system on the planet stores a `created_at` field. **None of that matters without a "now" to subtract from.**

Stored timestamps are historical when, facts about the past, frozen in a row. The hook gives the model present when, the live anchor for "right now, this turn." Without both, neither is useful for time reasoning:

- **Memory's `created_at`** = "this was true at T1"
- **Hook's per-message timestamp** = "the present moment is T2"
- **Model** = can subtract them, reason about elapsed time, detect drift, weight recency

Without the hook, even perfect memory timestamps are dead metadata for the model. It's like having a stopwatch that records lap times but no display for the current time. Lap times are noise without a reference. The model has historical when, but no "now" to make sense of it.

This is why the hook composes with any memory system, not just Mnemos, it's the foundation layer that makes stored timestamps actually useful. Mnemos benefits, generic SQLite memory benefits, even raw conversation history benefits. **It's the reference point everyone forgot to ship.**

The semantic-memory layer (what is true) gets all the attention in AI memory design. The episodic-memory layer (what happened, in what order, how recently) is where most systems are silent. The time hook is the smallest possible patch that adds the missing piece.

### The bigger claim: temporal cognition is a missing primitive

Zoom out. Everything above is about one small hook on one harness. The reason any of it matters is that it exposes a larger gap in how AI systems are built right now: **temporal cognition is not an optional enhancement layer for reasoning, it is a missing primitive.**

Reasoning operates on two axes. One is **space / context**: what is adjacent to what, what is in scope, what is being referred to. The other is **time**: what happened when, what follows what, what is still current, what has decayed, what has been true for long enough to matter. Every reasoning system needs both. LLMs out of the box have the first and not the second. They're trained on token sequences where time is implicit in ordering, then deployed into interactive, multi-session contexts where they must reason about *real* elapsed time in the outside world, and they do not have access to it.

They do not abstain. They confabulate. "Good morning" at midnight is not a glitch; it is the reasoning process trying to produce a coherent response with a missing primitive, filling the time-shaped hole with plausible hallucination, and reasoning downstream from the hallucinated premise.

Humans are so deeply embodied in time that it's invisible to them, like asking a fish about water. AI systems make time's load-bearing nature visible by failing in specific ways when it's absent. Those failures aren't edge cases. They're the normal output of a reasoning system trying to operate on a changing world without a clock. They show up in cognition (can't reason about decay, change, causation in time, or "is this still true"), in communication (can't coordinate rhythm, can't honor "I'll get to that later," can't match the other agent's cadence), and in memory (stored `created_at` fields are dead metadata without a live "now" to subtract from).

The field has been building larger and more capable reasoning systems without one of the two axes reasoning happens on. Nobody has noticed in earnest because LLMs are fluent enough to paper over the gap most of the time. This hook is a small practical patch for one harness. The architectural version of the fix, AI systems that know what time it is as a first-class input, not an occasional injection, is what the rest of the field still needs to ship.

### Causality without time is just correlation

The philosophical version of the argument is heavier than the engineering one. **Causal reasoning requires temporal cognition as a precondition.** Strip time out and causation collapses to mere co-occurrence.

Hume's 18th-century formalization of causation rests on three conditions: **contiguity in space and time, priority in time (cause precedes effect), and constant conjunction (regularity observed over time).** Two of the three are explicitly temporal; the third is implicit. Strip time out and none of them apply. You have events that sit next to each other in an undifferentiated present, and no way to tell which one produced which.

Pearl's modern formalization of causal inference (directed acyclic graphs, do-calculus, counterfactuals) is built on the same premise. Edges in a causal graph are *directed*, and direction represents causal flow. Causal flow is temporal, you don't traverse backward. The entire field of causal inference, which underpins epidemiology, econometrics, clinical trials, and modern ML interpretability, treats temporal ordering as irreducible.

Kant went further: in the *Critique of Pure Reason*, time (along with space) is an *a priori* structure of experience itself, not a feature of the external world we observe but a precondition for observing anything at all. On that reading, an entity without temporal cognition doesn't have diminished reasoning. It has a fundamentally different relationship to experience, in which experience-as-we-know-it isn't happening.

**The concrete implication for LLMs:**

Without temporal cognition, every causal claim an LLM produces is indistinguishable from mere co-occurrence. *"The build broke after the deploy"* and *"the build broke simultaneously with the deploy"* are the same observation. *"X happened because Y"* and *"X and Y appeared together in training data"* collapse to the same thing. The model produces causal-sounding language because it's trained on text that contains causal claims, but it has no mechanism to verify causation itself in a new situation, it is pattern-matching on causal language without the ability to ground it in observed ordering.

This is the root of a specific, well-documented LLM failure mode: **confabulating causal explanations**. When asked *"why did X happen?"* the model produces a plausible-sounding causal story. Sometimes the story is correct because the pattern was well-represented in training. Sometimes it's wrong because the model is surface-matching on causal syntax without the ability to independently verify cause-precedes-effect in the specific instance. Without temporal cognition the model cannot distinguish between *"I'm explaining real causation"* and *"I'm producing causal-shaped text."*

This escalates the thesis of this repository from quality-of-life patch to something sharper: **AI cannot do genuine causal reasoning without temporal cognition as a first-class primitive, and causal reasoning is a substantial fraction of what we actually want AI to do.** Debugging, medicine, science, economics, history, planning, consequences of decisions, all require causality, all require time. A hook that injects the current timestamp looks small because it *is* small. What it patches is not.

## License

MIT.
