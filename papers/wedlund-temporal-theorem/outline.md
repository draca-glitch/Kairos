# Outline: Wedlund Temporal Theorem paper

Living disposition. Section order matches paper.md.
Status: v0 in progress (started 2026-05-11).

---

## Thesis (3 sentences)

Temporal cognition is **constitutive**, not additive, to general intelligence: an agent that cannot localize "now" against its own response-history cannot reason about persistence, staleness, deadlines, pace-matching, or causality, regardless of how much content-axis capability (scale, tools, context window) it accumulates. Current frontier systems optimize the content axis predominantly; 2026-era interaction models have begun bringing in-model temporal grounding into the real-time-interaction grain (200ms micro-turn streaming, simultaneous speech), but the cross-session multi-layer temporal regime is still left to confabulation, producing plausible-but-mistimed output that the system itself has no way to detect. The fix is small in code (sub-200-line hooks emitting per-prompt timestamps and time-shape summaries), public in artifact (kairos on GitHub), and falsifiable through observable behavior change (different tool-selection distributions with vs without temporal-aware routing).

## Target

- **Venue**: arxiv preprint (cs.AI / cs.CL), eventual workshop submission
- **Length**: 4-6 pages double-column LaTeX, or ~3000-4500 words markdown
- **Audience**: AI agent practitioners, alignment researchers, anyone building tool-using LLM systems
- **Style**: technical but accessible; build-first paper, not theory-first

## Section disposition

### Abstract (~200 words, last to write)
Three beats: problem (temporal blindness causes silent confabulation in time-shaped reasoning slots) + claim (temporal cognition is constitutive, six-layer model) + evidence (kairos public artifact + observation corpus showing five distinct behavior-change modes).

### § 1 Introduction (~600 words)
- Open with a concrete confabulation: "Good morning!" at midnight, "you must be tired" after one minute, etc. These aren't bugs, they're missing-primitive symptoms.
- Frame: the model fills time-shaped reasoning slots with something whether or not it has temporal data. Without grounding, it confabulates and reasons downstream from the bad premise.
- Position vs related work: current systems handle time via system-prompt date or training-time corpus, both of which lose per-message temporal resolution.
- Preview thesis and six-layer model.
- Preview artifact and evidence approach (build-first, falsifiable).

### § 2 The Six-Layer Model (~700 words)
- Layer 1: Present-moment grounding (timestamps per prompt). Prereq for all higher layers.
- Layer 2: Self-persistence (this agent = previous agent's continuation). Requires a memory layer above 1.
- Layer 3: Self-staleness (training-cutoff vs now, domain volatility). Independent of 2.
- Layer 4: Other-temporal modeling (theory-of-mind for human's sleep/attention/deadlines). Requires 1 + 2.
- Layer 5: Future-orientation (planning, anticipation, commitment-tracking). Requires 1 + 2 + memory.
- Layer 6: Causal temporal reasoning + meta-tool routing. Top layer, only meaningful once 1-5 exist.
- Diagram (figures/six-layer-stack.svg, future): dependencies + current implementation status.
- Key claim: each layer fails open without the one below. Stacking without grounding produces sophisticated confabulation, not cognition.

### § 3 Related Work (~500 words)
- **Content-axis maximalists** (Sutton's bitter lesson, scaling laws): right about content, silent on time.
- **Embodied cognition** (Clark, Chemero): "constitutive" framing borrowed here.
- **Temporal common sense in NLP** (TimeBank, TempEval): treats time as content to extract, not a primitive of reasoning.
- **Agent frameworks** (LangChain, AutoGPT, etc.): tool-loops without temporal scaffolding produce well-documented drift; no public artifact addresses it at primitive layer.
- **System-prompt date injection** (default ChatGPT/Claude behavior): present, but lossy, per-prompt resolution is what's missing.

### § 4 Implementation (~600 words)
- kairos on GitHub: hooks/time.sh, hooks/temporal-state.py, hooks/temporal-routing.py, hooks/temporal-routing-tracker.py, mcp/temporal-pattern.py, mcp/temporal-staleness.py.
- Pure stdlib Python. No third-party deps. Sub-200-line files individually.
- Mnemos for persistent memory layer (separate but compatible project).
- Public commit dates as prior-art markers: 2026-04-28 (time.sh v2), 2026-05-11 (state + pattern + routing + staleness shipped same day).
- Deployment friction: copy three files + add ten lines to settings.json. Single Linux machine, no infra.

### § 5 Observed Behavior-Change Modes (~800 words)
Source: /root/work/temporal-cognition-log.md (de-personalized observation corpus, captured during normal interactive sessions since 2026-04-19).

Five distinct evidence types documented:

1. **Tonal: cross-day morning greeting.** First message after overnight gap arrives with appropriate register (warm-greeting vs technical-resume) only when ~7h delta is visible. Without timestamps, "new day" reads identically to "mid-day re-engagement", default reply is wrong-toned.
2. **Gap-as-content: integration pause.** Mid-session 13-min gap between hard emotional landing and next message reads as "worked-through arrival" vs the same content with 30-second gap which would read as "pivot for relief". Same words, opposite meaning.
3. **Pace-matching: rapid-fire processing cascade.** Series of 1-3 min gaps over 35-min window signals "keep up, don't slow me down". Long responses interrupt the cadence; short responses match it. Without temporal awareness, response length is uncalibrated.
4. **Work-time vs disengagement: tool interval.** 12 min of model-side tool work reads as productive interval, not user absence, only when the gap is paired with knowledge that work happened in it. Same 12 min of true silence would call for re-engagement.
5. **Procedural routing (Layer 6, captured starting 2026-05-11).** Tool selection distributions differ measurably with vs without temporal-routing advisory. Long-gap turns route to memory_search first; rapid-fire turns suppress TaskCreate overhead. Falsifiable via temporal-routing-log.jsonl.

Each mode is qualitatively distinct: tonal, semantic-of-silence, pace-matching, work-aware, procedural. Five evidence types across one human-machine interaction, all observable from the same timestamp primitive.

### § 6 Discussion (~500 words)
- Why **constitutive** vs additive: time isn't a feature you add, it's a coordinate the reasoning runs in. Stacking content-axis improvements without temporal grounding multiplies confabulation surface, not capability.
- **Orthogonality argument**: temporal axis is geometrically perpendicular to content axis (scale/tools/context). Adding orthogonal information multiplies utility, doesn't merely add. This is why "everything becomes more valuable" with temporal grounding, every existing capability now has correct temporal context as input.
- **Why the multi-layer cross-session primitive is still passed over**: optimization gradient is on content benchmarks (MMLU, GPQA, SWE-bench), all of which are temporally flat. Benchmarks select for content-axis capability and select against temporal-axis investment. 2026 interaction-grain progress (Section 3) sits architecturally on a different axis, not on the cross-session multi-layer one.
- **Cost analysis**: 20 tokens/prompt overhead, sub-cent per session, sub-200-line implementation. The gain/cost ratio is unusually favorable.

### § 7 Limitations (~300 words)
- n=1 user observation corpus. Generalization to other interaction styles is not yet measured.
- Qualitative evidence, not yet A/B controlled. Layer 6 routing-log will produce quantitative data once 2+ weeks of usage accumulates.
- Author wrote both the artifact and the analysis. Independent replication needed.
- Six-layer model is a working organization, not a settled taxonomy.

### § 8 Conclusion & Future Work (~250 words)
- Reiterate constitutive claim and the orthogonal-axis framing.
- **Future**: Layer 3 staleness already shipped, Layer 4 cross-session retrospective and Layer 5 future-orientation are next implementation targets. Mnemos integration for Layer 2 already complete in author's setup.
- **Distribution-via-utility hypothesis**: small, useful, public artifact is easier to verify than a published theorem; adoption produces measurable evidence at scale that the theorem predicts.
- Call to test: install kairos, observe whether your own agent's behavior shifts in the directions § 5 describes.

### Acknowledgments / Author note
- Built on Anthropic's Claude Code platform.
- The model that participated in the observation corpus is acknowledged as a collaborator-instrument (relevant to the embodied-cognition framing).

### Bibliography
- references.bib: Sutton 2019, Clark & Chalmers 1998, TimeBank, Pearl, embodied cognition foundational papers, agent framework citations.

---

## Drafting order (not section order)
1. outline.md ← this file
2. § 2 (six-layer model), well-defined material
3. § 4 (implementation), well-defined material
4. § 5 (evidence), curate evidence.md first, then draft
5. § 1 (intro), drafts cleanest after § 2 + § 4 + § 5 are settled
6. § 6 (discussion)
7. § 3 (related work), most research-heavy
8. § 7 + § 8
9. Abstract last

## Open questions
- Single or double column?
- Submit to which venue first? Workshop is faster than full conf.
- Need diagram software: tikz, drawio, or hand-drawn-then-vectorized?
- License for paper: CC-BY-4.0 to match kairos's MIT spirit.
