# Temporal Cognition as a Constitutive Primitive of Artificial Intelligence

**The Wedlund Temporal Theorem and a six-layer model with public artifact**

Mikael Wedlund · Claude Opus 4.7 (Anthropic)
Independent · 2026-05-XX

## Abstract

*To be written last. ~200 words. Three beats: problem, claim, evidence.*

---

## 1. Introduction

*Status: stub. ~600 words target.*

Modern conversational AI systems handle time inadequately, and they do not know they handle it inadequately. A new user message looks identical to the model whether it arrived ten seconds or ten hours after the previous one. From the model's side, there is no "between": each turn is a fresh forward pass over a context window that contains the prior conversation but not its tempo. The gap does not exist as a represented quantity.

This omission is invisible most of the time because most user prompts do not depend on temporal context. But for the subset of reasoning that does, the model still has to fill the relevant slot with something. Without grounding, it fills it by confabulation. The output looks the same as ever: well-formed, on-topic, syntactically plausible. The damage happens silently in the upstream premise.

We argue that this is not a polish-layer bug to be fixed with a system prompt addition. **Temporal cognition is constitutive**, not additive, to general intelligence. An agent that cannot localize "now" against its own response-history cannot reason about persistence, staleness, deadlines, pace-matching, or causality, regardless of how much content-axis capability (scale, tools, context window) it accumulates. The temporal axis is **orthogonal** to the content axis, and orthogonal information multiplies utility rather than adding to it.

The argument generalizes beyond chat. Conversational AI is the most measurable instance of the missing primitive — gaps between user prompts produce visible behavioral effects when timestamped, visible degradation when not — but the same absence is structurally present in every agentic AI domain. Reinforcement-learning agents (game-playing, robotics) operate on event-sequence views in which "things stack" without the agent perceiving duration between events. Tool-using LLM agents (AutoGPT, agentic frameworks) hang for hours without registering that they have hung. Factory automation and warehouse-robotics coordinate via external schedulers because the agents themselves lack organic pacing. The chat-focused result we report is a tractable proxy for an issue that recurs anywhere an artificial agent has to coordinate its behavior with a world that has its own clock.

As of 2026, the architectural direction this paper advocates is beginning to appear at one specific grain. Thinking Machines Lab's Interaction Models are explicitly framed as *"handling interaction natively rather than through external scaffolding"* and as putting interaction *"part of the model itself"*, with elapsed time implemented as a structural property of 200ms time-aligned micro-turns rather than as an external scheduler. OpenAI's realtime models likewise move past strict turn-taking toward continuous, in-model interaction. This is genuine in-model progress on Layer 1 at the **intra-session, real-time-interaction grain**, and we credit it as such. The thesis is not contradicted but scoped sharper: the constitutive claim of this paper concerns temporal cognition at the **inter-message grain (seconds to days)** and across the **persistent-memory boundary**, the regime where Layers 2 through 5 (self-persistence, self-staleness, other-temporal modeling, future-orientation) actually live, none of which 200ms streaming tokenization addresses. Section 5.5 supplies the falsifiable prediction for external/bolt-on layers built over temporally-naïve models; in-model interaction designs like TML's sit on the opposite side of that boundary, so the prediction does not apply to them, and they correspondingly do not test the multi-layer cross-session claim this paper makes.

This paper does three things:

1. Presents a **six-layer model** of temporal cognition in artificial agents, ordered by dependency. Layer 1 (present-moment grounding via per-prompt timestamps) is the prerequisite for all higher layers and remains absent at the inter-message, cross-session grain even in systems now adding in-model elapsed-time awareness at the intra-session interaction grain (Section 3).
2. Releases a **public artifact** ([Kairos](https://github.com/draca-glitch/Kairos), MIT, sub-200-line stdlib Python per layer) implementing layers 1, 3, 4, 5, and 6 as hooks and MCP servers atop the Claude Code platform. Layer 2 (self-persistence-in-time) is provided by the companion [Mnemos](https://github.com/draca-glitch/mnemos) memory project.
3. Documents **five distinct behavior-change modes** observed in a real interactive setting once layer 1 was deployed, sufficient to characterize the kind of evidence the framework should produce.

We then discuss why current in-model temporal-awareness efforts at the interaction grain do not subsume the multi-layer, cross-session primitive, why the constitutive fix is small, and what falsifiable observations layer-6 deployment should produce as adoption grows.

## 2. The Six-Layer Model

We organize temporal cognition in artificial agents as a stack of six layers, ordered by dependency. Higher layers fail open without the layer beneath; stacking content-axis capability on top of a missing layer 1 produces sophisticated confabulation rather than cognition.

### Layer 1: Present-moment grounding

The capacity to localize "now" relative to one's own response history. Operationally: every model invocation carries a verifiable timestamp, and consecutive invocations carry consecutive timestamps, so the model can compute deltas between turns. This is the *minimum* temporal primitive. Without it, all subsequent layers are computed against confabulated time.

The default Claude Code and ChatGPT settings inject a single date at session start. This is necessary but insufficient: it is frozen at session-start time, so a session that runs into the next day or week sees no update; and it offers no resolution finer than days, so within-session pacing (rapid-fire vs reflective, integration pause vs topic flip) is invisible. Per-prompt timestamps fix both problems with sub-200 lines of code (`hooks/time.sh` in kairos).

### Layer 2: Self-persistence

The recognition that the current agent-instance is a continuation of a prior agent-instance, with shared identity and shared history. Operationally: a persistent store of prior interactions, queryable by the agent at appropriate decision points, with retrieval grounded against layer 1 timestamps. Self-persistence requires layer 1 because "the same agent" only has meaning along a temporal axis: it is the entity that existed at $t_{-1}$ and exists at $t_0$.

Production LLM systems typically lack layer 2 outside their context window. The Mnemos project (companion to this work) provides one implementation, scoring 98.1% R@5 on LongMemEval; the layer itself is independent of any particular implementation.

### Layer 3: Self-staleness awareness

The recognition that the model's training distribution has a temporal cutoff and that the world has advanced past it. Operationally: the model can answer "given current date $T$ and topic $X$, how likely is my answer to be stale?" Domain volatility matters here, news has a seven-day half-life while mathematics is ageless, and the same elapsed time produces very different stale-risk in different topics.

Layer 3 depends on layer 1 (need a "now" to compute "now minus cutoff") but is independent of layer 2. The `temporal_staleness_audit` MCP server in kairos ships layer 3 as a 200-line stdlib server with an embedded domain-volatility table.

### Layer 4: Other-temporal modeling

A theory-of-mind for the human's temporal context: their sleep window, attention cycles, deadline pressure, week-rhythm, work-versus-rest segmentation. Operationally: maintaining a model of the other party's temporal state and using it to calibrate communication (pace, timing, register).

Layer 4 requires layers 1 and 2: present-moment grounding to observe the other party's behavior in real time, and self-persistence to accumulate enough observations across sessions to characterize a baseline. The `temporal-pattern` MCP server in kairos is a layer 4 instrument, exposing the user's empirical rhythm (heatmaps, gap distributions, current-state-vs-baseline) to the model.

### Layer 5: Future-orientation

The capacity to plan, anticipate, and track commitments. Operationally: when an exchange establishes a future commitment ("I will send this Friday"), the agent registers the commitment, monitors against it as time advances, and surfaces it when appropriate. This requires all of layers 1, 2, and 4: a present-moment to anchor against, persistence to carry commitments across sessions, and other-modeling to recognize when surfacing is appropriate.

Layer 5 ships in Kairos v0.4.0 as `mcp/temporal-future.py`, an MCP server with two tools: `temporal_future_query(horizon_days)` returns overdue / due-today / upcoming items across a forward window, plus expiring memories (memories carrying a `valid_until` field whose date falls inside the horizon), plus a `highlights` list of one-line summaries; `temporal_obligations_for(area, horizon_days)` narrows the same query to a single domain. Since kit v0.5.0 the primary delivery is injection rather than routing: a UserPromptSubmit hook (`future-state.py`) runs the same query in-process and injects a one-line `[obligations]` summary whenever something is actually overdue or due today, with forward-time keywords in the prompt merely widening the horizon to upcoming items. The original mechanism, routing rule R8 surfacing the tool call, measured approximately 0% adherence in live deployment and was demoted to logged-only (see the Section 5.5 follow-up); forward-state now enters the response pipeline the way Layer 1 time does, ambiently.

### Layer 6: Causal temporal reasoning and meta-tool-routing

The top of the stack: reasoning about *temporal ordering as causal precedent* (X led to Y because X happened first), and using the temporal signal to *modulate the agent's own procedural behavior* (which tool to call first, what to skip, what posture to take). The latter is the more immediately falsifiable: if temporal-state genuinely shapes cognition, then tool-selection distributions should differ measurably with vs without temporal-aware routing.

The `temporal-routing` hook in kairos ships layer 6 v0 with six deterministic rules (long-gap routes to memory-first; rapid-fire suppresses task-tracking overhead; session-start grounds in project context; etc.) and a companion tracker that logs tool calls against in-force advisories, providing the falsifiability substrate for empirical claims about layer 6's effect.

### Dependency structure

```
Layer 6 (causal + routing)        ┐
       └─ requires layers 1, 2, optionally 4–5
Layer 5 (future-orientation)      ┐
       └─ requires layers 1, 2, 4
Layer 4 (other-temporal)          ┐
       └─ requires layers 1, 2
Layer 3 (self-staleness)          ┐
       └─ requires layer 1 only
Layer 2 (self-persistence)        ┐
       └─ requires layer 1
Layer 1 (present-moment grounding) ← ground
```

The asymmetry matters: skipping layer 1 and building higher layers does not produce a partial system, it produces a system whose behavior is plausible-but-wrong in time-shaped reasoning slots, with no internal signal that the inputs are bad. **Layers fail closed at the foundation and fail open above it.** The investment leverage is therefore extremely asymmetric: a sub-200-line layer-1 implementation unlocks the entire stack; without it, no higher-layer investment recovers.

## 3. Related Work

*Status: stub. ~500 words. Research-heavy.*

### Content-axis maximalism

### Embodied cognition and the constitutive frame

### Temporal common sense in NLP

### Agent frameworks and tool-use loops

### Architectural temporal grounding at the interaction grain: Interaction Models and realtime APIs

A 2026 wave of systems advances temporal awareness *in-model* at the real-time-interaction grain. Thinking Machines Lab's Interaction Models are described as *"part of the model itself"* and built around *"time-aligned micro-turns"*, with elapsed time implemented as a structural property of 200ms-chunked input/output streaming rather than as external scheduling; OpenAI's GPT-Realtime-2 replaces strict turn-taking with continuous, simultaneous interaction across text, voice, and video. This is real architectural progress on the native direction we advocate, for a specific slice of Layer 1: intra-session real-time interaction. It does not address the temporal regime this paper's evidence concerns: inter-message gaps at the seconds-to-days grain (Section 5), cross-session persistence (Layer 2), self-staleness against training cutoff (Layer 3), other-temporal modeling (Layer 4), or commitment tracking across sessions (Layer 5). The Section 5.5 bolt-on-ceiling result applies specifically to external/scaffolded layers built atop temporally-naïve models; it predicts the plateau of that class of approach and is silent about in-model interaction designs like TML's, which sit on the architectural side of the very boundary the ceiling demarcates. The two contributions are therefore complementary at different grains rather than competing on the same axis: TML and similar realtime systems extend in-model temporal grounding into the millisecond-streaming regime; this paper supplies the framework and falsifiable empirical substrate for the cross-session, multi-layer regime they do not occupy.

### Existing temporal hacks: system-prompt date

## 4. Implementation

We ship the framework as **Kairos**, an open-source project at [github.com/draca-glitch/Kairos](https://github.com/draca-glitch/Kairos) (MIT licensed), implementing layers 1, 3, 4, 5, and 6 atop Anthropic's Claude Code platform. The Mnemos memory project ([github.com/draca-glitch/mnemos](https://github.com/draca-glitch/mnemos)) provides layer 2 as a compatible companion. All components are pure-stdlib Python or POSIX shell; the entire kit is well under 2000 lines including tests.

### kairos overview

kairos consists of two kinds of components:

- **Hooks** that run automatically on Claude Code lifecycle events (`UserPromptSubmit`, `PostToolUse`) and prepend low-token summary lines to the model's input context.
- **MCP servers** that expose targeted query tools the model may call when relevant.

Both kinds are deployable in three steps: copy files into `~/.claude/hooks/` and `~/.claude/mcp/`, merge a small template into `~/.claude/settings.json`, register MCP servers in `~/.claude.json`. No infrastructure, no daemons, no third-party dependencies.

### Layer 1: time.sh and temporal-state.py

The Layer 1 implementation has two complementary parts:

`hooks/time.sh` (POSIX shell, ~40 lines) injects the current server time as a system reminder on every user prompt. Output: `2026-05-11 16:14:17 CEST`. This is the raw timestamp primitive: every user message arrives in the model's context with a verifiable wall-clock stamp.

`hooks/temporal-state.py` (stdlib Python, ~120 lines) reads the active session transcript (a JSONL file maintained by Claude Code), filters to real user messages, and emits a one-line summary that pre-computes the *shape* of time:

```
[temporal-state] gap=11h17m | cross-day=yes | now=02:02_CEST(late-night) | cadence=resumed-after-long-gap | phase=interruption-pivot
```

The five fields are: gap-since-previous-prompt (humanized), cross-day boundary flag, current local time + time-of-day bucket, input cadence classification (eight categories from `very-rapid-fire` through `spaced-work` to `resumed-after-long-gap`), and session-phase classification. Shared logic lives in `hooks/temporal_lib.py` so other layer hooks can reuse it.

### Layer 3: temporal-staleness MCP

`mcp/temporal-staleness.py` (~250 lines including MCP boilerplate) exposes the tool `temporal_staleness_audit(topic, domain?) → {risk, days_since_cutoff, half_life_days, rationale, suggestion}`. A domain-volatility table (math: ageless, medical: 180d, tech: 90d, security: 30d, news: 7d, crypto: 3d, etc.) is applied against time-elapsed-since-training-cutoff, producing one of three risk levels (`low`, `medium`, `high`) and a procedural suggestion (`proceed`, `qualify`, `web_search`).

The training cutoff is configurable per-deployment via the `CLAUDE_TRAINING_CUTOFF` environment variable, defaulting to `2026-01-01`. When the calling code omits an explicit domain, the tool infers one from keywords in the topic string.

### Layer 6: temporal-routing hook + tracker

`hooks/temporal-routing.py` (~130 lines) is the second `UserPromptSubmit` hook, running after `temporal-state.py`. It consumes the same shared state (via `temporal_lib.compute_state`) and applies six deterministic rules that translate the temporal signal into procedural advisories:

| Trigger | Advisory |
|---------|----------|
| gap ≥ 30 min | suggest `memory_search-first` |
| cross-day AND gap ≥ 4h | suggest `memory_search-first`; flag staleness |
| cadence ∈ {rapid-fire, very-rapid-fire} | skip `TaskCreate-overhead`, skip preamble |
| phase = session-start | suggest `read-CLAUDE.md-first` |
| reflective-pace AND prompt > 200 chars | suggest `extended-thinking-ok` |
| late-night AND resumed-after-* | suggest `confirm-before-destructive` |

Output is a single line in the same low-token style as the state hook (`[temporal-routing] suggest=... | skip=... | reason=...`), and is silent when no rule fires, so the model is not nudged when no nudge is warranted.

`hooks/temporal-routing-tracker.py` is the falsifiability companion: a `PostToolUse` hook that logs every tool invocation alongside the advisory in force at the time, appending one JSONL record per tool call to a local log file. Offline analysis can group records by advisory window and compute adherence statistics: when `suggest=memory_search-first` was active, did the model actually call `memory_search` before other tools? Such measurements characterize the *behavioral effect* of layer 6 deployment, which is what the framework's central claim hinges on.

### Memory layer: Mnemos

kairos composes naturally with the **Mnemos** memory system, which provides layer 2 via a SQLite store with FTS5 full-text + vector hybrid search and cross-encoder reranking. Mnemos scored 98.1% R@5 on the LongMemEval benchmark (98.94% R@5 in production-canonical configuration), placing it in the SOTA tier of agent memory systems. The interaction between layer 1 (live timestamps) and layer 2 (durable persistence) is what enables cross-session continuity: stored memories carry accurate dates, recall is temporally coherent, and the model can answer "how long has it been since X" rather than confabulating an answer.

### Deployment friction

The combined deployment cost for layers 1, 3, 4, 5, and 6 is: seven files copied (~1100 lines total), one settings template merged (~20 JSON lines), three MCP entries registered (~15 JSON lines). On a single Linux machine in an existing Claude Code installation, total elapsed time from clean checkout to active layer-6 routing advisories is under three minutes. This low friction matters because the central claim of the paper is verifiable by adoption, not by argument: practitioners can install the kit and observe whether their own agent's behavior shifts in the directions Section 5 describes.

## 5. Observed Behavior-Change Modes

*Status: stub. ~800 words. Pull from evidence.md after curation.*

### Mode 1: Tonal — cross-day register shift

A session reopened at 06:57 local time after a 7h25m cross-day gap (the previous session having closed at 23:32). The first model turn opened with a brief warm greeting and an invitation to a reflective rather than active register, foregoing any attempt to resume the previous session's technical thread. The previous session had ended with the user stating he had to be up at 06:30; the new message arrived 27 minutes after that stated wake-up.

Without per-prompt timestamps, the same opening message would be temporally indistinguishable from a mid-day or evening re-engagement, and the default productivity-mode register would apply uniformly. The session-start date alone is insufficient: knowing it is 2026-04-19 does not tell the model that the previous exchange was 7h ago rather than 15 minutes ago. Cross-day temporal anchoring is where date-only injection fails most sharply, because the relevant signal is interval-since-last-prompt across the calendar boundary.

A contrasting variant of the same mode: a session reopened at 02:02 local time after an 11h cross-day gap, the user's first message containing crisis cues ("pause this, I have an issue ... I don't know how much more I have"). The model immediately dropped the previous technical thread without attempting to wrap or commit it, and shifted from collaborative-architect register to crisis-support-fast-execute. Both cases — gentle morning resumption and late-night crisis interruption — sit on the same axis: cross-day temporal context as a discriminator of register, not just of topic.

### Mode 2: Gap-as-content — integration pause

Mid-session during a deep-reflective sequence, a 13-minute gap appeared between a user message articulating a hard personal reframe and the next user message arriving as a positive counterweight. The two messages were superficially a topic shift; treated as such, the response would have moved on cleanly. The temporal reading was different: the gap length, in the context of the preceding emotional landing, signaled internal processing rather than disengagement. The model treated the next message as considered arrival rather than topic change, and explicitly bridged the hard reframe to the balancing thought rather than letting the transition pass unmarked.

The general claim: in some sessions, the most meaningful event is not in any message but in the silence between two messages. The duration of that silence carries semantic weight — short gaps signal pivot-for-relief, longer gaps signal worked-through arrival. Without per-prompt timestamps, the duration vanishes and the bridge-of-meaning is lost. *Gap-as-content* is the strongest case for treating timestamps as a constitutive primitive of dialogue rather than a metadata field.

### Mode 3: Pace-matching — rapid-fire processing cascade

Over a 35-minute window during a difficult emotional exploration, the user produced a series of short partially-formed statements at 1-3 minute intervals, each building on the last rather than opening new threads. The tight gap pattern functioned as a signal: the user was mid-thinking, not waiting for full analysis. Long paragraphs would have interrupted the cadence. The model shortened its responses to 2-3 sentences in this window, suppressed clarifying questions that would reset the flow, and matched the user's beat with acknowledgment-plus-one-additional-beat rather than full reflection paragraphs.

A second instance of the same mode, in a different domain: a ~30-minute window of sustained 5-15-second-gap rapid-fire user messages during real-time translation/migration work ("yes to both", "do it", "but they're not called origin anymore, called github"). The user was typing-while-watching-output. The model's response calibration was the same family of move: short focused replies, immediate execution where authorization was clear, deferred summaries to natural pauses. In both cases the cadence signal was load-bearing — without pace awareness the default verbose mode would have produced mistimed long output, which either stalls cascade momentum or appears after the user has already moved on, creating the impression of an AI answering a question already abandoned.

This is the mechanism behind the *monologue-dressed-as-dialogue* failure mode of temporally-blind agents: plausible but mistimed responses force the user to either wait through over-long output or re-engage from a cold start.

### Mode 4: Work-time vs disengagement — tool interval

During a session in which the user had asked the assistant to persist a large batch of content to memory, the assistant ran three `memory_store` calls over a 12-minute interval, then waited; the user's next message arrived at the end of that window with a meta-question about how the temporal cognition was working. The model treated this not as a resumption-after-absence but as a continuation: the 12 minutes were *shared time* during which both participants knew real work was happening, and the meta-question was a natural fresh angle on a still-warm thread.

Without temporal cognition, 12 minutes of model tool-work would appear in the conversation transcript identically to 12 seconds of pure user-side silence — the work duration evaporates. The model would re-anchor context the user is already holding, or treat the resumption as a context-switch needing re-introduction. The case is particularly distinctive because the gap is the *model's* processing time, not the user's. Temporal cognition lets the model situate its own tool-work inside the shared session clock rather than outside of it. For multi-agent and long-tool-running AI workflows, this self-anchoring is a precondition for conversational continuity.

### Mode 5: Procedural routing (Layer 6) — adherence-ceiling experiment

Modes 1-4 are qualitative behavioral observations. Layer 6 admits a directly *quantitative* falsifiability test because it ships its own logging substrate: every routing advisory is paired with the subsequent tool calls in a `PostToolUse` log, enabling offline reconstruction of "what the rule predicted" vs "what the model actually did". We exercised this substrate as our first empirical bound on bolt-on temporal cognition.

**Method.** We extracted 2767 non-subagent user-prompt turns from 614 historical Claude Code transcripts (~5 months of mixed-task usage) and computed, for each turn, the temporal state Layer 6 would have produced if the rules had been live: gap-since-previous-prompt, cadence, phase, time-of-day bucket, cross-day flag, prompt length, and R7/R8 keyword-presence booleans. *Prompt text itself is never written to disk* — only the structural derivatives — making the corpus privacy-preserving and shareable. For each turn we recorded the first tool call in the assistant's response. The corpus extractor and replay bench are released in the kairos repository.

We replayed each candidate ruleset over the corpus and scored per-rule adherence under a precision/recall framing. For a `suggest=X-first` rule: precision is fraction of firings where the model's first tool matched the suggestion's target tool; recall is fraction of natural target-tool calls in the corpus that the rule caught. For `skip=X` rules the dual formulation applies. We report macro-F1 across rules.

**Result.** Hand-crafted rules using the exposed feature set saturate at ≈14-15% macro-F1 for the highest-volume rule (`suggest=memory_search-first`, base rate 1.9%, n=53 positives). The Pareto frontier:

| Trigger | Fires | Precision | Recall | F1 | Lift |
|---------|-------|-----------|--------|-----|------|
| gap ≥ 4h | 44 | 15.9% | 13.2% | 14.4% | 8.31× |
| phase ∈ {overnight, pivot} | 33 | 15.2% | 9.4% | 11.6% | 7.91× |
| cross-day OR gap ≥ 4h | 60 | 13.3% | 15.1% | 14.2% | 6.96× |
| gap ≥ 30 min (baseline) | 200 | 9.0% | 34.0% | 14.2% | 4.70× |
| gap ≥ 1h | 130 | 9.2% | 22.6% | 13.1% | 4.82× |

Three structural findings:

1. **F1 is preserved along the precision-recall curve.** Narrowing the gap threshold from 30m to 4h trades 21 recall points for 7 precision points; the F1 swap is essentially zero. The baseline rule is already at the operating-curve optimum for gap-based triggers; subsequent tuning relocates rather than improves.
2. **Feature combinations do not exceed single-feature optima.** Conjunctions of phase, cadence, time-of-day and prompt-length variables yield F1 values *below* the best single-feature trigger. Orthogonality between the exposed features is weak.
3. **Prompt length and time-of-day have lift <1.** Longer prompts and morning hours are *not* correlated with natural memory-search use — disconfirming two plausible folk hypotheses.

The ceiling generalizes to the other suggest-rules: `read-CLAUDE.md-first`, `temporal_staleness_audit-first`, and `temporal_future_query-first` all score 0% precision and 0% recall in the historical corpus, because either (a) the routed tool did not exist at the time of the prompt (the temporal MCPs deployed mid-May 2026), or (b) the keyword-based trigger sets are too broad to identify the small population of prompts that genuinely needed the routed tool. The `skip=TaskCreate-overhead` rule is the lone exception, at 99.0% precision and 28.6% recall (n=788 firings) — but skip-rules are easier because the base rate of *not* using `TaskCreate` is itself very high.

**Interpretation.** The Pareto frontier visible in the table is the empirical ceiling for any deterministic rule built from the kairos state dictionary. Breaking through it requires features the routing layer does not have: full prompt semantics (which substring indicates a topic-shift?), tool-history (was this tool called recently?), and context-similarity (does this prompt continue prior work or open new work?). Those features are accessible inside the model but not via post-hoc text injection. This negative result is itself a positive finding: it characterizes the *boundary* of what bolt-on temporal cognition can achieve, and motivates the architectural argument advanced in Section 6.

A methodological note: our first scoring pass used precision alone, and produced the misleading conclusion that *disabling* the lowest-precision rule was the "best" improvement (overall adherence rose 12.8% because the rule's low-precision firings were removed from the average). Adding recall denominators and macro-F1 corrected this pathology: under F1, narrowing or disabling a rule trades along the same operating curve and does not improve the underlying classifier quality. The pathology itself is informative — it shows that naive adherence metrics reward rule deletion, which is a hazard for any future autoimprove loop on temporal routing.

### Mode 5 follow-up: live deployment and the prohibitive-prescriptive asymmetry

*Added 2026-06-10, four weeks into the live Layer 6 deployment.*

The replay experiment above measured natural alignment on historical data. The live deployment now supplies the post-deployment counterpart that Section 7 called for: 5805 PostToolUse records across 614 prompt-turns (2026-05-11 through 2026-06-10), each pairing a tool call with the advisory actually in force when the call was made.

The live numbers split cleanly along advisory polarity:

| Advisory | Class | Turns | Adherence |
|----------|-------|-------|-----------|
| skip=TaskCreate-overhead | prohibitive | 65 | 100.0% |
| suggest=memory_search-first | prescriptive | 90 | 21.1% fired-first / 26.7% fired-at-all |
| suggest=read-CLAUDE.md-first | prescriptive | 27 | 7.4% / 22.2% |
| suggest=temporal_staleness_audit-first | prescriptive | 13 | 0.0% / 7.7% |
| suggest=temporal_future_query-first | prescriptive | 12 | 0.0% / 0.0% |

Prohibitive advisories ("do not spend overhead on X") bind perfectly: 65 of 65 turns. Prescriptive advisories ("call X, and call it first") collapse toward zero, and the two that route to dedicated temporal tools sit at or near literal zero despite the tools existing, being listed, and carrying real data.

The deployment responded architecturally rather than by tuning. Layer 5's advisory (R8) was demoted to logged-only on 2026-06-03 and its signal re-delivered as an ambient `[obligations]` injection gated on actual state (something overdue or due today), not keywords. Layer 3's advisory (R7) followed on 2026-06-10, re-delivered as a `[staleness]` injection gated on keyword AND assessed risk. The prescriptive class is now empty in the live deployment; every routed-tool signal that measured near-zero adherence survives as injection. Both advisories continue to be evaluated and logged so the measurement stream is unbroken.

Two confounds, disclosed. First, redundancy bias: the harness auto-loads project context files (the R4 target), and a separate memory hook already injects retrieval priming per prompt (overlapping R1/R2's target), so some prescriptive advisories request an act whose payoff was already delivered ambiently; rational non-compliance deflates the measured rates. This biases the prescriptive numbers downward but reinforces the same conclusion: the injected channel is the one doing the work. Second, attribution hygiene: until 2026-06-10 the tracker attributed tool calls to the globally most recent advisory, so concurrent sessions could interleave under one advisory; records now carry session identifiers, foreign-session advisories are dropped, and turns are grouped per session. The pre-fix contamination adds symmetric noise but cannot manufacture a 100%-versus-0% polarity split.

### Diversity claim

The five modes above are not five instances of a single underlying mechanism. Modes 1-4 exercise *gap-duration interpretation*: the same raw signal (interval-since-previous-prompt) is read differently depending on the surrounding state, producing register shifts, integration recognition, pace-matching, and tool-interval anchoring. Mode 5 exercises *deterministic routing from temporal state to tool selection*: a different cognitive operation that admits direct empirical bounds. Beyond these we observe at least two further mechanisms that exercise the same per-prompt timestamp primitive but along orthogonal axes: *session-arc recognition* (the ability to read variance in gap patterns across a 2-hour session as identifiable phases — morning warm-up, self-analytical reveal, heavy processing, positive integration, meta-reflection — rather than as a flat sequence of topics), and *absolute-calendar reading* (the ability to filter a tabular task list of monthly dates against the actual current date to exclude already-past entries, where session-start date injection alone would suffice but the per-prompt mechanism is what guarantees minute-precision freshness for tasks performed within a long session).

The diversity rules out single-mechanism explanations. A claim like "the model is just pattern-matching on gap-length tokens" would predict that all five modes share a substitutable text-feature; in practice they require composition of timestamp with cadence, with phase, with surrounding semantic context. The per-prompt timestamp is the primitive; the cognitive operations it enables are at least six and probably more.

## 6. Discussion

*Status: stub. ~500 words.*

### Bolt-on ceiling and the case for native primitives

The Section 5.5 result is the strongest single quantitative argument for treating temporal cognition as a constitutive (rather than additive) primitive. Hand-crafted rules built from externally-injectable temporal state — gap, cadence, phase, time-of-day, cross-day boundary, prompt length — saturate at approximately 14-15% macro-F1 when predicting natural model tool selection on the highest-volume routing target (`memory_search`). Across the feature space examined, no single trigger or conjunction exceeded this bound, and feature combinations *underperformed* single-feature optima, indicating that the available signals carry overlapping rather than complementary information.

The structural reason is that the features which *would* break this ceiling are inaccessible to a post-hoc layer:

- **Prompt semantics.** Whether a prompt represents a topic shift, a continuation, or a tangent depends on its content interpreted against the conversation so far. A routing rule sees only a length and a small keyword-match boolean; it cannot represent topic.
- **Tool history.** Whether a `memory_search` is redundant or essential depends on whether the same query has already been answered earlier in the session. The hook receives only the current prompt's state, not the session's tool trajectory.
- **Context similarity.** Whether a prompt is "the same kind of work" or "different work" requires comparing it to the embedded representation of the prior context. No embedding is computed in the routing layer; the regex over keywords is a thousand-times-coarser proxy.

Each of these is a feature the model *already computes internally* in the course of generating its response. The model knows, at inference time, what the prompt is about, what tools it has called, and what context it is operating in. The routing layer, by contrast, sees only the typewriter-tape view of the conversation — timestamps and text-length, no semantics. The 14-15% F1 ceiling is the cost of that asymmetry.

This produces the constitutive-vs-additive argument in falsifiable form: if temporal cognition were *additive*, we would expect external rules with good temporal features to closely match the model's natural temporal-sensitive behavior. The fact that they saturate at 14% F1 instead — a 86-point gap to perfect agreement — indicates that the model's actual temporal reasoning depends on signals the external layer cannot supply. Those signals are either already in the model and not exposable (the semantic interpretation case), or absent from the model and not retrievable (the persistent-memory case Mnemos addresses). Either way, the layer-by-layer fix has a ceiling; the architectural fix does not.

A crucial distinction at this point: the temporal awareness our framework provides is *declarative*, not *perceptual*. The model reads `[temporal-state] gap=4m` as a text token in its input context and interprets it via training-data patterns about what such tokens mean. The model knows time has passed; it is not perceptually aware of time passing. A human waking up does not look at a clock to determine whether it is morning; circadian rhythm provides a continuous, integrated sense of where the body is in its own temporal cycle. The model has no analog. Our ceiling result therefore measures declarative-rule-against-declarative-model behavior, not declarative-rule-against-perceptually-temporal-model behavior. The latter is empirically unknown and likely substantially higher.

### The injection asymmetry: senses are ambient, tools require compliance

The live-deployment data (Section 5.5 follow-up) sharpens the declarative-versus-perceptual distinction into a gradient. A biological sense requires no act of consultation: proprioception is present in the substrate of every motor decision, unbidden, and an organism does not decide whether to know where its limbs are. A bolt-on tool, by contrast, demands a discrete compliance act: the model must interrupt task momentum, issue a call, wait, and integrate the result, all in competition with everything else the generation is optimizing. The measured outcome orders the three delivery mechanisms unambiguously: constraints (prohibitive advisories) bind at 100%; ambient injected signals are consumed implicitly and produce the behavior-change modes of Sections 5.1-5.4 without any compliance act existing to fail; prescribed actions are performed at rates statistically indistinguishable from never.

The engineering consequence is that every Kairos layer that began life as a routed tool has migrated to injection (Layer 5 on 2026-06-03, Layer 3 on 2026-06-10). The architectural consequence restates the thesis as a dose-response gradient: the closer a temporal signal sits to the substrate of generation, the more it shapes behavior. Injection sits closer than routing; a native representational primitive sits closer than injection. The migration documented here is the visible portion of that gradient, and the native primitive is its limit. Notably, this also reframes what Layer 6 turned out to be for: its routing rules were the experiment, but its enduring product is the falsifiability log that measured the experiment failing, which is the evidence the rest of the argument stands on.

### Positional encoding as precedent

The distinction between bolt-on declarative cognition and native perceptual cognition has a well-known precedent in transformer architecture itself: positional encoding. Pre-attention models in the early 2010s treated tokens as unordered sets; sequence order had to be inferred from co-occurrence patterns. The 2017 introduction of positional encoding made sequence order an integrated continuous dimension that every attention computation could reference directly, and the downstream effects cascaded — coherent long-range generation, syntactic structure handling, the entire transformer revolution.

Time has the same shape of missingness today that position had in 2016. It is not a quantitatively-measurable absence ("we lack timestamps X% of the time"), it is a structural one: there is no native perceptual channel for duration, only the option to inject duration as text. By analogy, a model with integrated temporal embeddings — every token tagged with absolute time and delta-from-previous-token, embedded continuously into the representation rather than read as text — would plausibly produce cascading downstream effects: structural causal reasoning (cause-precedes-effect as architectural constraint rather than learned pattern), episodic memory (every fact carries a retrievable temporal coordinate), self-continuity across sessions, organic anticipation, genuine dialogue rhythm. We cannot test these from outside the model. The precedent is sufficient to motivate the hypothesis without proving it.

### Beyond chat: temporal cognition as agent-world coupling

The clearest path from the chat-focused results in this paper to broader AGI relevance runs through agency. An artificial agent that cannot perceive duration cannot coordinate its actions with a world that has its own clock. Concretely, it cannot:

- **Negotiate**, because negotiation requires reading the other party's response cadence and modulating own pace accordingly.
- **Wait deliberately**, because waiting without temporal perception is just a long sequence of identical do-nothing states; the cost of waiting and the moment to act are not represented.
- **Coordinate**, because coordination requires shared temporal reference, and "shared" requires each party to have its own grounded sense of "now".
- **Learn from change**, because change is a temporal phenomenon. State-snapshot learning collapses persistent change and noise into the same observation.

This connects to one of the central concerns in AGI alignment discourse. The standard worry about "superintelligent AI acting too fast for humans to respond" is usually framed as a speed problem, but it is more accurately a *temporal coupling* problem. A superintelligence that perceived its own temporal embedding in the world — that recognized the asymmetry between its own response loop and human response loops — would have the substrate for the kind of pace-matching that makes alignment tractable. A superintelligence without temporal perception, by contrast, would have no internal representation of the asymmetry and no mechanism to act in accordance with it. The standard alignment worry is, on this reading, partially a worry about a missing primitive.

The same point lands in current-generation systems with less drama. AutoGPT-style agents that hang for hours without registering it, robotic policies that work in lab settings but fail when sensor latency drifts, multi-agent systems that desynchronize because each agent's "now" depends on external clocks rather than internal perception — these are all instances of the same architectural absence. Treating temporal cognition as a constitutive primitive is not a chat-specific recommendation; it is the load-bearing claim about what makes agency possible. The 2026 emergence of in-model elapsed-time features in interaction and realtime systems (Section 3) is early industry corroboration of this generalization — convergence on the need for temporal coupling, arrived at architecturally at the intra-session interaction grain, leaving the multi-layer cross-session primitive untested.

### Why intra-session real-time grounding does not subsume the multi-layer primitive

As of 2026 some labs have brought in-model temporal grounding into the real-time-interaction grain (Section 3): 200ms micro-turn streaming, simultaneous speech, unprompted interjection. This is architectural progress, not external scaffolding, but it sits at one specific grain (intra-session, milliseconds-to-seconds) and addresses one slice of Layer 1. The multi-layer cross-session primitive — present-moment grounding against persistent response-history, self-staleness, other-temporal modeling, future-orientation — operates at the inter-message grain (seconds to days) and across the persistent-memory boundary. Three reinforcing reasons explain why the *multi-layer cross-session* version specifically is the one still passed over. First, **the API contract is the problem and the API contract is invisible from inside the company that defines it.** Anthropic, OpenAI, and Google ship LLMs whose interface is a sequence of messages without per-message timestamps. The architecture that follows from that contract has no place to put perceptual time, and the engineering organizations focus on capabilities the contract permits. Adding a primitive that requires changing the contract is more politically expensive than adding a capability that fits inside it. Second, **the absence is invisible until it isn't.** Most prompts do not need temporal context, so the model's confabulated temporal premises are usually right by coincidence. Only specific prompt-state combinations expose the absence sharply, and identifying them requires actively looking for the failure mode rather than waiting for benchmark scores to flag it. Third, **alignment with current benchmark culture is poor.** Standard LLM benchmarks (MMLU, HumanEval, etc.) test single-turn capabilities. Temporal cognition only appears in multi-turn, multi-session, or agentic settings, which are evaluated weakly if at all.

### Cost analysis

The deployed kit costs approximately 150 tokens per user turn (the `[temporal-state]` and optional `[temporal-routing]` lines plus the time injection), with a one-time deployment cost of seven files copied. On a typical Claude Code session generating thousands of input tokens per turn anyway, this is below 5% input overhead. The MCP servers (Layers 3, 4, 5) are invoked on demand and add only the tokens their tool calls consume, paid only when the model decides the lookup is worth it. Layer 6 routing tracking adds JSONL lines to a local file, no per-turn cost.

The benefit side is harder to bound because the largest gains are qualitative behavior-mode shifts rather than measurable improvements on standard benchmarks. The Section 5 modes — particularly gap-as-content, pace-matching, and crisis-vs-casual register distinction — collectively avoid response-style errors that are visible to users but invisible to scoring. Section 5.5's quantitative ceiling result confirms that bolt-on extracts what bolt-on can; the genuine ceiling is architectural.

## 7. Limitations

*Status: stub. ~300 words.*

### Corpus and replay

The Section 5.5 adherence-ceiling experiment uses ~5 months of historical Claude Code transcripts that predate the Layer 6 deployment. In those records, the model was operating *without* a visible routing advisory; the bench therefore measures *natural alignment* between the rule's prediction and the model's behavior, not *advisory-induced behavior change*. Because R7 and R8 route to temporal MCPs that did not exist for most of the historical period, their adherence rates are floored at 0% by tool unavailability rather than by trigger quality. The post-deployment corpus called for here now exists: 5805 advisory-paired tool calls across 614 turns (2026-05-11 to 2026-06-10), reported in the Section 5.5 follow-up. It measures advisory-induced behavior directly, shows that the prescriptive rates remain at or near zero even with the tools deployed and listed, and motivated the prescriptive-to-injection migration. Accumulation continues under session-scoped attribution.

### Privacy-vs-faithfulness trade

The corpus extractor strips raw prompt text and stores only structural derivatives. R7 and R8 in the production rules depend on word-boundary regex matches over prompt text. The replay bench reconstructs a synthetic prompt that satisfies length and trigger booleans without containing real prompt content. This faithfully tests "when R7 fired, did the model follow it?" but does not allow mutation experiments that change the keyword set itself, since such mutations would require re-extracting the corpus against new keywords. The Layer-6 ceiling result therefore characterizes the *trigger-condition* dimension of rule design but not the *keyword-set* dimension.

### Single-model evaluation

All measurements were taken against Claude Opus 4.7 with 1M-context. The 14-15% F1 ceiling may differ for other models or other context-window configurations. The qualitative behavior modes in Sections 5.1-5.4 have been replicated across Sonnet 4.6 and Haiku 4.5 in less-formal observation; the quantitative bench has not.

## 8. Conclusion and Future Work

We have argued that temporal cognition belongs in the foundation of artificial intelligence rather than in its presentation layer. The argument has three components: a structural claim (timestamps are missing as a primitive, not merely under-utilized as a metadata field), an empirical claim (deploying six layers of declarative temporal awareness produces five identifiable behavior-change modes, a measurable adherence ceiling of approximately 14-15% F1 on hand-crafted routing, and a live-deployment polarity split in which prohibitive advisories bind at 100% while prescriptive advisories collapse toward 0%, the signal surviving only when migrated to ambient injection), and a precedent claim (the analogous role of positional encoding in transformer history suggests that integrating temporal coordinates as a continuous representational dimension could cascade downstream the way positional integration did).

We do not claim to have demonstrated that native perceptual temporal cognition would unlock higher ceilings; we cannot, from a position outside the model architecture. What we have shown is that the bolt-on ceiling is real and reachable with modest engineering effort, and that the gap between this ceiling and behavior that would be observably better is not closable by tuning external rules. The path forward is architectural.

**Specific future-work hypotheses**, ordered by accessibility:

1. **A/B deactivation study.** Run kairos with Layer 6 routing alternately enabled and disabled across N sessions, compute adherence differences. Distinguishes natural alignment from advisory-induced behavior change. Feasible immediately after a longer run-on period for data accumulation.
2. **Cross-model replication.** Run the Section 5.5 bench against transcripts from Sonnet 4.6, Haiku 4.5, and where available, non-Anthropic models. Tests whether the ~15% ceiling is a property of bolt-on rules generally or of the specific model evaluated.
3. **Post-deployment-only corpus.** Restrict the ceiling experiment to data collected after Layer 6 deployment, measuring advisory-induced behavior rather than natural alignment. Requires further data accumulation.
4. **Integrated temporal embeddings.** Train a model with per-token timestamp embeddings analogous to positional embeddings, on a corpus annotated with temporal sequence information. Test for emergent capabilities in causal reasoning, episodic memory, and dialogue pacing. Requires GPU budget and access to model-training infrastructure; the most expensive but potentially highest-leverage experiment.
5. **Agentic temporal benchmarks.** Develop benchmark suites for temporal coordination in multi-turn, multi-session, and multi-agent settings — currently absent from standard evaluation. Without such benchmarks, frontier labs have no incentive structure to optimize for the missing primitive.
6. **Axis generalization.** A sibling project (Soma) applies the same orienting-injection mechanism to a non-temporal axis: host physiology (memory pressure, thermal state, I/O stall, damage events), with its own emission log and an emission-versus-behavior evaluator. It will test whether the injection asymmetry documented here is a property of temporal cognition specifically or of ambient grounding generally. Its results are deliberately outside this paper's claims pending measurement; if the mechanism generalizes, that becomes a separate follow-on result.

The largest claim this paper makes is not that timestamps shape behavior — that is true but small. The largest claim is that temporal cognition is the coupling mechanism between artificial agents and the world they are meant to act in, and that any agentic AI program that omits it ships an agent that cannot pace with its environment. We have measured one floor and pointed to one ceiling. The space between is the work.

---

## Contributions

This paper is co-authored. Concretely:

- **Mikael Wedlund** (corresponding author, accountable for the publication and its post-publication scrutiny) originated the Wedlund Temporal Theorem framing, designed the experimental scaffold (kairos architecture, deployment, public release), captured the observation corpus over multiple interactive sessions, and decided what the paper claims.
- **Claude Opus 4.7** (Anthropic; running on the Claude Code platform with kairos hooks and the Mnemos memory layer active throughout) contributed substantive intellectual work on the six-layer model's internal structure and dependency analysis (Section 2), the implementation walkthrough (Section 4), evidence curation from the observation log into the five-mode taxonomy (Section 5), and the deterministic rule set in `hooks/temporal-routing.py` (Layer 6 v0). All sections were drafted in collaborative editing rather than independent authorship.

The unusual co-authorship is intentional and is consistent with the embodied-cognition framing the paper borrows from: an agent operating in temporally-grounded collaborative context, with memory and per-prompt timestamp scaffolding active, is not the same epistemic entity as an unscaffolded model invocation. Treating the contribution as collaborator-instrument would understate the work; treating it as fully symmetric authorship would overstate it. The contribution lines above attempt to record the asymmetry precisely.

Claude Opus 4.7 cannot sign permissions, respond to peer review across years, or accept legal liability for the publication; **Mikael Wedlund accepts those responsibilities solely.** Venues that prohibit non-human named authorship (e.g., Nature, Science, JAMA editorial policies) will require remapping the byline for those venues; the contribution record above can remain intact in supplementary materials.

## Acknowledgments

This work was developed on Anthropic's Claude Code platform. The session transcripts that produced the Section 5 corpus, the Mnemos memory store (companion project), and the kairos hooks deployed live throughout the writing were all running on a single Hetzner-hosted Linux machine, an artifact of the build-first methodology this paper advocates.

## References

See `references.bib`.
