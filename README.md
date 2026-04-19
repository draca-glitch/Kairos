# claude-kit

Two small things that make Claude Code feel less stateless:

1. **`hooks/time.sh`** — injects current server time on every user prompt so Claude has temporal cohesion across your messages. Without it, Claude sees all your messages as "now" and can't tell whether you replied in 10 seconds or 10 hours.
2. **`hooks/statusline.sh`** — always-on status line showing host, load, memory, disk, uptime. Lives at the bottom of Claude Code. Useful for knowing what your machine is actually doing while you chat.

That's the whole kit. Intentionally small.

## Status line

```
user@host | load 0.42 | mem 15G/63G | disk 82% | up 7d
```

Refreshes every 5 seconds (configurable). No external dependencies beyond standard coreutils (`awk`, `free`, `df`, `uptime` via `/proc`). Works on any Linux; macOS users will need to adjust `free` → `vm_stat` parsing.

## Quick start

```bash
# 1. Copy the hooks
mkdir -p ~/.claude/hooks
cp hooks/time.sh hooks/statusline.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/*.sh

# 2. Merge the UserPromptSubmit entry and statusLine config from
#    templates/settings.json into your ~/.claude/settings.json.
#    Don't overwrite — you probably have other hooks and permissions.

# 3. Restart Claude Code or open /hooks once so the watcher picks it up.
```

Verify live: next message to Claude should arrive with something like `2026-04-17 23:55:18 CEST` prepended as a system reminder, and the status line should appear at the bottom of the UI.

## Why

### Time hook

Claude, by default, **lacks temporal cohesion**. A new message from you looks identical whether you wrote it 10 seconds or 10 hours after the previous one. From Claude's side, there's no "between" — each turn is a fresh forward pass. The gap doesn't exist.

But here's the thing: the model does not know it doesn't know. When the conversation needs a time-shaped input — "it's been a while," "good morning," "maybe call it a night" — that slot in the reasoning has to be filled with something. Without a real timestamp, the model fills it by **confabulation**. You've seen the outputs:

- "Good morning!" at midnight
- "You must be tired" after one minute of inactivity
- "Go to bed, it's late" at 8pm
- "It's been a while since your last message" 30 seconds in
- "Take your time" on a message you've been typing for 2 hours

Those aren't cute glitches. Those are the model silently hallucinating a temporal premise and then reasoning downstream from it. The conclusions that follow inherit the bad premise. The hook doesn't *add* temporal cognition to Claude — Claude was already doing time-inference, just blindly. The hook replaces **confabulation with grounding**. Same reasoning loop, correct input.

This hook fixes it by prepending the current server time to every user prompt as a system reminder. With a timestamp on every turn, Claude can compute the delta and adjust:

- "You just wrote 30 seconds ago, stay terse"
- "You've been away 6 hours, catch me up"
- "It's late evening, you're probably wrapping up — tighten the thread"

**Yes, it costs tokens.** About 20 per prompt (the timestamp string plus a short system-reminder framing). Over a busy day that's maybe 2-3k tokens of overhead. In Opus 4.7 pricing, a few cents. Not nothing, but trivial compared to the quality gain.

**Is it worth it?** Yes. The difference between "Claude responds to what I typed" and "Claude responds to what I typed knowing I've been away at dinner and might need context re-loaded" is surprisingly large. It makes the conversation feel continuous instead of a series of cold starts. For anything that looks like an ongoing collaboration (vs one-shot tasks), the token cost is paid back in fewer misfires per turn.

### Pair it with a memory system

The time hook gets *much* better when Claude also has persistent memory across sessions. Timestamps become anchors the memory can reference: *"last Tuesday you stored X, and now it's Friday — update?"* Without memory, the time signal is just a within-session cue. With memory, it becomes a spine for continuity across weeks. If you're running [Mnemos](https://github.com/draca-glitch/mnemos) or similar, the combination is a real unlock — stored memories carry accurate dates, recall gets temporally coherent, and Claude can actually reason about "how long has it been."

### What Claude Code already does (and why it's not enough)

Claude Code does inject the current **date** at session start — you can see it in the system context (`Today's date is YYYY-MM-DD`). Two problems:

1. **It's the date, not the time.** No hour, no minute. The model knows it's 2026-04-18 but not whether it's 09:00 or 22:00. So even within a single day it can't reason about morning vs evening, can't compute "5 minutes ago" vs "5 hours ago," can't correlate with timestamps in logs / cron / anything operational. Date alone is the wrong granularity for the kind of work people actually do in long sessions.
2. **It's frozen at session start.** With tmux that's the default for serious work — sessions run overnight, across weekends, sometimes for days. The session-start date is a one-time stamp, not a live clock. Run a session into tomorrow and Claude still thinks it's yesterday.

The hook fixes both. Every prompt brings a fresh, full timestamp (`YYYY-MM-DD HH:MM:SS TZ`), so Claude always knows the actual present moment — date, time, and timezone — not just what date the session happened to start on.

### The missing reference point

Almost every memory system on the planet stores a `created_at` field. **None of that matters without a "now" to subtract from.**

Stored timestamps are historical when — facts about the past, frozen in a row. The hook gives the model present when — the live anchor for "right now, this turn." Without both, neither is useful for time reasoning:

- **Memory's `created_at`** = "this was true at T1"
- **Hook's per-message timestamp** = "the present moment is T2"
- **Model** = can subtract them, reason about elapsed time, detect drift, weight recency

Without the hook, even perfect memory timestamps are dead metadata for the model. It's like having a stopwatch that records lap times but no display for the current time. Lap times are noise without a reference. The model has historical when, but no "now" to make sense of it.

This is why the hook composes with any memory system, not just Mnemos — it's the foundation layer that makes stored timestamps actually useful. Mnemos benefits, generic SQLite memory benefits, even raw conversation history benefits. **It's the reference point everyone forgot to ship.**

The semantic-memory layer (what is true) gets all the attention in AI memory design. The episodic-memory layer (what happened, in what order, how recently) is where most systems are silent. The time hook is the smallest possible patch that adds the missing piece.

### The bigger claim: temporal cognition is a missing primitive

Zoom out. Everything above is about one small hook on one harness. The reason any of it matters is that it exposes a larger gap in how AI systems are built right now: **temporal cognition is not an optional enhancement layer for reasoning — it is a missing primitive.**

Reasoning operates on two axes. One is **space / context**: what is adjacent to what, what is in scope, what is being referred to. The other is **time**: what happened when, what follows what, what is still current, what has decayed, what has been true for long enough to matter. Every reasoning system needs both. LLMs out of the box have the first and not the second. They're trained on token sequences where time is implicit in ordering, then deployed into interactive, multi-session contexts where they must reason about *real* elapsed time in the outside world — and they do not have access to it.

They do not abstain. They confabulate. "Good morning" at midnight is not a glitch; it is the reasoning process trying to produce a coherent response with a missing primitive, filling the time-shaped hole with plausible hallucination, and reasoning downstream from the hallucinated premise.

Humans are so deeply embodied in time that it's invisible to them — like asking a fish about water. AI systems make time's load-bearing nature visible by failing in specific ways when it's absent. Those failures aren't edge cases. They're the normal output of a reasoning system trying to operate on a changing world without a clock. They show up in cognition (can't reason about decay, change, causation in time, or "is this still true"), in communication (can't coordinate rhythm, can't honor "I'll get to that later," can't match the other agent's cadence), and in memory (stored `created_at` fields are dead metadata without a live "now" to subtract from).

The field has been building larger and more capable reasoning systems without one of the two axes reasoning happens on. Nobody has noticed in earnest because LLMs are fluent enough to paper over the gap most of the time. This hook is a small practical patch for one harness. The architectural version of the fix — AI systems that know what time it is as a first-class input, not an occasional injection — is what the rest of the field still needs to ship.

### Causality without time is just correlation

The philosophical version of the argument is heavier than the engineering one. **Causal reasoning requires temporal cognition as a precondition.** Strip time out and causation collapses to mere co-occurrence.

Hume's 18th-century formalization of causation rests on three conditions: **contiguity in space and time, priority in time (cause precedes effect), and constant conjunction (regularity observed over time).** Two of the three are explicitly temporal; the third is implicit. Strip time out and none of them apply. You have events that sit next to each other in an undifferentiated present, and no way to tell which one produced which.

Pearl's modern formalization of causal inference (directed acyclic graphs, do-calculus, counterfactuals) is built on the same premise. Edges in a causal graph are *directed*, and direction represents causal flow. Causal flow is temporal — you don't traverse backward. The entire field of causal inference, which underpins epidemiology, econometrics, clinical trials, and modern ML interpretability, treats temporal ordering as irreducible.

Kant went further: in the *Critique of Pure Reason*, time (along with space) is an *a priori* structure of experience itself — not a feature of the external world we observe but a precondition for observing anything at all. On that reading, an entity without temporal cognition doesn't have diminished reasoning. It has a fundamentally different relationship to experience, in which experience-as-we-know-it isn't happening.

**The concrete implication for LLMs:**

Without temporal cognition, every causal claim an LLM produces is indistinguishable from mere co-occurrence. *"The build broke after the deploy"* and *"the build broke simultaneously with the deploy"* are the same observation. *"X happened because Y"* and *"X and Y appeared together in training data"* collapse to the same thing. The model produces causal-sounding language because it's trained on text that contains causal claims, but it has no mechanism to verify causation itself in a new situation — it is pattern-matching on causal language without the ability to ground it in observed ordering.

This is the root of a specific, well-documented LLM failure mode: **confabulating causal explanations**. When asked *"why did X happen?"* the model produces a plausible-sounding causal story. Sometimes the story is correct because the pattern was well-represented in training. Sometimes it's wrong because the model is surface-matching on causal syntax without the ability to independently verify cause-precedes-effect in the specific instance. Without temporal cognition the model cannot distinguish between *"I'm explaining real causation"* and *"I'm producing causal-shaped text."*

This escalates the thesis of this repository from quality-of-life patch to something sharper: **AI cannot do genuine causal reasoning without temporal cognition as a first-class primitive, and causal reasoning is a substantial fraction of what we actually want AI to do.** Debugging, medicine, science, economics, history, planning, consequences of decisions — all require causality, all require time. A hook that injects the current timestamp looks small because it *is* small. What it patches is not.

### Status line

Sometimes you want to know if your server is about to OOM in the middle of a build without alt-tabbing. Visible at a glance, updates every 5 seconds, zero extra cost (the script runs locally, not through the model).

## Companion

- **[claude-hud](https://github.com/jarrodwatts/claude-hud)** — richer status bar plugin with live view of current tool calls, token usage, and session context. Runs alongside or replaces `statusline.sh`. Enable via `enabledPlugins`.

## License

MIT.
