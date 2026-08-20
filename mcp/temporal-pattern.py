#!/usr/bin/env python3
"""
MCP server: temporal_pattern_query.

Lets Claude query the user's actual temporal activity patterns derived
from session transcripts. Sibling to kairos's hooks/temporal-state.py:
that one tells Claude what's happening *right now*, this one tells
Claude what the user's pattern *usually* looks like, so pacing/tone
decisions can be made against a baseline rather than heuristics.

Tool: temporal_pattern_query
  metric:
    overview                  - summary: session count, date range, peak hours, current state
    heatmap_hour              - activity counts bucketed 0-23 (UTC-local converted)
    heatmap_dow               - activity counts bucketed by day of week
    session_durations         - distribution of session length in minutes
    gap_distribution          - distribution of gaps between sessions
    current_state_vs_baseline - now vs historical baseline for this hour/dow
  days_back (default 60): look-back window

Reads ~/.claude/projects/-<cwd>/*.jsonl (or any path under
~/.claude/projects/), filters to real user-typed prompts, aggregates.

Pure stdlib. Newline-delimited JSON-RPC 2.0 over stdin/stdout.

Registration in ~/.claude.json (project-scoped mcpServers):
    "temporal-pattern": {
      "type": "stdio",
      "command": "python3",
      "args": ["~/.claude/mcp/temporal-pattern.py"]
    }
"""

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECTS_DIR = Path(os.environ.get("CLAUDE_PROJECTS_DIR", str(Path.home() / ".claude" / "projects")))


# --- Transcript scanning ---


def _import_is_real_user_prompt():
    """Reuse hooks/temporal_lib.is_real_user_prompt when reachable.

    The MCP server may be deployed alongside the hooks (sibling directory in
    the repo, or both under ~/.claude/) or standalone. We try a handful of
    likely paths and fall back to an inline copy if none resolve, so the
    server stays self-contained even when distributed without the hooks.
    """
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "hooks",                       # repo layout: mcp/ + hooks/
        Path.home() / ".claude" / "hooks",           # canonical deployed path
        Path(os.environ.get("CLAUDE_KIT_HOOKS_DIR", "")),
    ]
    for c in candidates:
        if c and (c / "temporal_lib.py").exists():
            if str(c) not in sys.path:
                sys.path.insert(0, str(c))
            try:
                from temporal_lib import is_real_user_prompt as _shared
                return _shared
            except Exception:
                continue
    return None


_shared_filter = _import_is_real_user_prompt()


def _is_real_user_prompt(event: dict) -> bool:
    if _shared_filter is not None:
        return _shared_filter(event)
    # Inline fallback, only used when temporal_lib is not reachable.
    if event.get("type") != "user":
        return False
    msg = event.get("message") or {}
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if isinstance(content, str):
        return "<task-notification>" not in content
    if isinstance(content, list):
        has_text = any(isinstance(c, dict) and c.get("type") == "text" for c in content)
        has_tool_result = any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content)
        if has_tool_result:
            return False
        if has_text:
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    if "<task-notification>" in (c.get("text") or ""):
                        return False
            return True
    return False


def _iter_ring_prompts(days_back: int):
    """Yield (utc_dt, ring_stem) from thread-ring files (adapter harnesses:
    Codex, Grok). Opt-in via KAIROS_PATTERN_SOURCES containing 'ring'."""
    state_dir = Path(os.environ.get(
        "CLAUDE_KIT_STATE_DIR", str(Path.home() / ".claude" / "state")
    ))
    ring_dir = state_dir / "thread-rings"
    if not ring_dir.exists():
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    for ring in ring_dir.glob("*.json"):
        try:
            data = json.loads(ring.read_text(encoding="utf-8"))
            for item in data.get("timestamps") or []:
                try:
                    dt = datetime.fromisoformat(str(item))
                except Exception:
                    continue
                if dt.tzinfo is None or dt < cutoff:
                    continue
                yield (dt, f"ring:{ring.stem}")
        except Exception:
            continue


def _iter_user_prompts(days_back: int):
    """Yield (utc_dt, session_id) for each real user prompt within the window.

    Sources: Claude transcripts (always) plus, when KAIROS_PATTERN_SOURCES
    includes 'ring', the thread-ring timestamps written by harness adapters.
    Default stays transcripts-only."""
    sources = os.environ.get("KAIROS_PATTERN_SOURCES", "transcripts")
    if "ring" in {s.strip() for s in sources.split(",")}:
        yield from _iter_ring_prompts(days_back)
    if not PROJECTS_DIR.exists():
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    for jsonl in PROJECTS_DIR.rglob("*.jsonl"):
        try:
            mtime = datetime.fromtimestamp(jsonl.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                continue
            with open(jsonl, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if not _is_real_user_prompt(e):
                        continue
                    ts = e.get("timestamp")
                    if not ts:
                        continue
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except Exception:
                        continue
                    if dt < cutoff:
                        continue
                    session_id = e.get("sessionId") or jsonl.stem
                    yield (dt, session_id)
        except Exception:
            continue


def _local(dt: datetime) -> datetime:
    return dt.astimezone()


# --- Metric computations ---


def _build_corpus(days_back: int):
    """Materialize one pass through the transcript corpus."""
    prompts = list(_iter_user_prompts(days_back))
    prompts.sort(key=lambda p: p[0])
    return prompts


def _metric_overview(prompts):
    if not prompts:
        return {"total_prompts": 0, "note": "no transcript data in window"}

    sessions = defaultdict(list)
    for dt, sid in prompts:
        sessions[sid].append(dt)

    session_durations_min = []
    for sid, dts in sessions.items():
        if len(dts) >= 2:
            d = (max(dts) - min(dts)).total_seconds() / 60
            session_durations_min.append(d)

    hours = Counter(_local(dt).hour for dt, _ in prompts)
    peak_hours = sorted(hours.items(), key=lambda kv: -kv[1])[:3]

    dows = Counter(_local(dt).strftime("%a") for dt, _ in prompts)
    peak_dows = sorted(dows.items(), key=lambda kv: -kv[1])[:3]

    first = _local(prompts[0][0])
    last = _local(prompts[-1][0])

    return {
        "total_prompts": len(prompts),
        "total_sessions": len(sessions),
        "date_range": {
            "first": first.strftime("%Y-%m-%d %H:%M %Z"),
            "last": last.strftime("%Y-%m-%d %H:%M %Z"),
        },
        "avg_session_duration_min": round(sum(session_durations_min) / len(session_durations_min), 1) if session_durations_min else None,
        "median_session_duration_min": round(sorted(session_durations_min)[len(session_durations_min) // 2], 1) if session_durations_min else None,
        "peak_hours_of_day": [{"hour": h, "count": c} for h, c in peak_hours],
        "peak_days_of_week": [{"day": d, "count": c} for d, c in peak_dows],
    }


def _metric_heatmap_hour(prompts):
    counts = Counter(_local(dt).hour for dt, _ in prompts)
    total = sum(counts.values()) or 1
    return {
        "scale": "local-hour-of-day (0-23)",
        "buckets": [{"hour": h, "count": counts.get(h, 0), "share": round(counts.get(h, 0) / total, 3)} for h in range(24)],
    }


def _metric_heatmap_dow(prompts):
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    counts = Counter(_local(dt).strftime("%a") for dt, _ in prompts)
    total = sum(counts.values()) or 1
    return {
        "scale": "day-of-week",
        "buckets": [{"day": d, "count": counts.get(d, 0), "share": round(counts.get(d, 0) / total, 3)} for d in days],
    }


def _metric_session_durations(prompts):
    sessions = defaultdict(list)
    for dt, sid in prompts:
        sessions[sid].append(dt)

    durations_min = []
    for dts in sessions.values():
        if len(dts) >= 2:
            durations_min.append((max(dts) - min(dts)).total_seconds() / 60)

    if not durations_min:
        return {"sessions": 0}

    durations_min.sort()
    n = len(durations_min)
    return {
        "sessions_with_multiple_prompts": n,
        "min_min": round(durations_min[0], 1),
        "p25_min": round(durations_min[n // 4], 1),
        "median_min": round(durations_min[n // 2], 1),
        "p75_min": round(durations_min[(3 * n) // 4], 1),
        "p90_min": round(durations_min[int(0.9 * n)], 1) if n >= 10 else None,
        "max_min": round(durations_min[-1], 1),
        "avg_min": round(sum(durations_min) / n, 1),
    }


def _metric_gap_distribution(prompts):
    sessions_first_last = []
    sessions = defaultdict(list)
    for dt, sid in prompts:
        sessions[sid].append(dt)
    for dts in sessions.values():
        if dts:
            sessions_first_last.append((min(dts), max(dts)))
    sessions_first_last.sort()

    gaps_min = []
    for i in range(1, len(sessions_first_last)):
        gap_s = (sessions_first_last[i][0] - sessions_first_last[i - 1][1]).total_seconds()
        if gap_s > 0:
            gaps_min.append(gap_s / 60)

    if not gaps_min:
        return {"between_sessions": 0}

    gaps_min.sort()
    n = len(gaps_min)
    return {
        "between_sessions": n,
        "min_min": round(gaps_min[0], 1),
        "p25_min": round(gaps_min[n // 4], 1),
        "median_min": round(gaps_min[n // 2], 1),
        "p75_min": round(gaps_min[(3 * n) // 4], 1),
        "max_min": round(gaps_min[-1], 1),
        "avg_min": round(sum(gaps_min) / n, 1),
    }


def _metric_current_vs_baseline(prompts):
    now_local = datetime.now().astimezone()
    h = now_local.hour
    dow = now_local.strftime("%a")

    hours_counter = Counter(_local(dt).hour for dt, _ in prompts)
    dow_counter = Counter(_local(dt).strftime("%a") for dt, _ in prompts)
    total = sum(hours_counter.values()) or 1

    hour_share = hours_counter.get(h, 0) / total
    dow_share = dow_counter.get(dow, 0) / total
    avg_hour_share = 1 / 24
    avg_dow_share = 1 / 7

    hour_ratio = hour_share / avg_hour_share if avg_hour_share > 0 else 0
    dow_ratio = dow_share / avg_dow_share if avg_dow_share > 0 else 0

    interpretation_hour = (
        "typical-or-busier" if hour_ratio >= 1.0
        else "below-typical" if hour_ratio >= 0.5
        else "rare-for-this-hour" if hour_ratio >= 0.2
        else "very-rare-for-this-hour"
    )
    interpretation_dow = (
        "typical-or-busier" if dow_ratio >= 1.0
        else "below-typical" if dow_ratio >= 0.5
        else "rare-for-this-dow" if dow_ratio >= 0.2
        else "very-rare-for-this-dow"
    )

    last_prompt = prompts[-1][0] if prompts else None
    gap_since_last_min = None
    if last_prompt:
        gap_since_last_min = round((datetime.now(timezone.utc) - last_prompt).total_seconds() / 60, 1)

    return {
        "now": now_local.strftime("%Y-%m-%d %H:%M %Z"),
        "current_hour": h,
        "current_dow": dow,
        "activity_at_this_hour": {
            "share_of_total": round(hour_share, 3),
            "ratio_vs_uniform": round(hour_ratio, 2),
            "interpretation": interpretation_hour,
        },
        "activity_on_this_dow": {
            "share_of_total": round(dow_share, 3),
            "ratio_vs_uniform": round(dow_ratio, 2),
            "interpretation": interpretation_dow,
        },
        "gap_since_last_prompt_min": gap_since_last_min,
        "total_prompts_in_window": len(prompts),
    }


METRICS = {
    "overview": _metric_overview,
    "heatmap_hour": _metric_heatmap_hour,
    "heatmap_dow": _metric_heatmap_dow,
    "session_durations": _metric_session_durations,
    "gap_distribution": _metric_gap_distribution,
    "current_state_vs_baseline": _metric_current_vs_baseline,
}


def tool_temporal_pattern_query(args: dict) -> dict:
    metric = args.get("metric", "overview")
    days_back = int(args.get("days_back", 60))
    if metric not in METRICS:
        return {"error": f"unknown metric: {metric}. valid: {sorted(METRICS.keys())}"}
    prompts = _build_corpus(days_back)
    result = METRICS[metric](prompts)
    return {"metric": metric, "days_back": days_back, "data": result}


# --- MCP protocol ---


TOOL_DEFINITIONS = [
    {
        "name": "temporal_pattern_query",
        "description": (
            "Query the user's actual temporal activity patterns derived from session transcripts. "
            "Lets Claude calibrate pacing/tone against the user's real rhythm rather than heuristics. "
            "Metrics: overview (summary), heatmap_hour (activity by hour-of-day), heatmap_dow "
            "(by day-of-week), session_durations (distribution in minutes), gap_distribution "
            "(between-session gaps), current_state_vs_baseline (now vs typical for this "
            "hour/dow + gap-since-last-prompt). days_back defaults to 60."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": list(METRICS.keys()),
                    "default": "overview",
                },
                "days_back": {
                    "type": "integer",
                    "default": 60,
                    "minimum": 1,
                    "maximum": 365,
                },
            },
        },
    }
]


# --- MCP protocol support -------------------------------------------------
# Dual-era (spec 2026-07-28 "Backward Compatibility with Initialization-Based
# Versions"). 2026-07-28 removed the initialize handshake: a modern client
# declares its protocol version in per-request _meta, servers MUST implement
# server/discover, and every result carries resultType. A legacy client still
# opens with initialize and never announces a version per request, so absence
# of _meta is the legacy case and must not be treated as a mismatch.
# Serving both from one loop is what the spec's compatibility matrix calls a
# dual-era server -- the only server kind that works with both client eras.
PROTOCOL_MODERN = "2026-07-28"
PROTOCOL_LEGACY = "2024-11-05"
# The intermediate published revisions still open with initialize and share the
# legacy tools/list + tools/call wire format, so the legacy path serves them
# correctly. Refusing a version we can in fact speak would turn a working
# client into a hard failure for no benefit.
PROTOCOL_INTERMEDIATE = ["2025-06-18", "2025-03-26"]
SUPPORTED_VERSIONS = [PROTOCOL_MODERN, *PROTOCOL_INTERMEDIATE, PROTOCOL_LEGACY]
SERVER_NAME = "temporal-pattern"
SERVER_VERSION = "1.1.0"
SERVER_INSTRUCTIONS = "Query temporal patterns in this user's own interaction history: session cadence, hour and weekday heatmaps, gap distribution, and current-vs-baseline drift."
META_PROTOCOL = "io.modelcontextprotocol/protocolVersion"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"
CACHE_TTL_MS = 3600000
ERR_UNSUPPORTED_PROTOCOL = -32022  # renumbered from -32004 in 2026-07-28


def _server_info():
    return {"name": SERVER_NAME, "version": SERVER_VERSION}


def _requested_version(params):
    """The protocol version a modern client declares on this request.

    None means the client declared nothing at all, which is the legacy era --
    never a mismatch, or we would reject every 2024-11-05 request.
    """
    return ((params or {}).get("_meta") or {}).get(META_PROTOCOL)


def _result(body):
    """Attach the fields 2026-07-28 requires to a result body.

    Purely additive, so one shape serves both eras: legacy clients ignore
    unknown keys, and the spec directs modern clients to read a missing
    resultType as "complete".
    """
    out = dict(body)
    out.setdefault("resultType", "complete")
    meta = dict(out.get("_meta") or {})
    meta.setdefault(META_SERVER_INFO, _server_info())
    out["_meta"] = meta
    return out


def _unsupported_version(id_, requested):
    """UnsupportedProtocolVersionError; `supported` is what lets a client retry."""
    return {
        "jsonrpc": "2.0", "id": id_,
        "error": {
            "code": ERR_UNSUPPORTED_PROTOCOL,
            "message": "Unsupported protocol version",
            "data": {"supported": SUPPORTED_VERSIONS, "requested": requested},
        },
    }


def _read_msg():
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        return json.loads(line)
    except Exception:
        return None


def _send(obj):
    # One wrap point rather than per-call-site: every result gains resultType
    # and serverInfo here. An initialize result is identified by its
    # protocolVersion field and left exactly as it was, since only a legacy
    # client ever sees one.
    res = obj.get("result")
    if isinstance(res, dict) and "protocolVersion" not in res:
        obj = dict(obj)
        obj["result"] = _result(res)
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    sys.stderr.write("temporal-pattern-mcp v1.1.1 starting (dual-era: " + ", ".join(SUPPORTED_VERSIONS) + ")\n")
    sys.stderr.flush()
    while True:
        msg = _read_msg()
        if msg is None:
            break
        method = msg.get("method", "")
        id_ = msg.get("id")
        params = msg.get("params", {})

        if id_ is None:
            continue

        requested = _requested_version(params)
        if requested is not None and requested not in SUPPORTED_VERSIONS:
            _send(_unsupported_version(id_, requested))
            continue

        if method == "server/discover":
            # MUST-implement in 2026-07-28, and the stdio backward-compat probe:
            # a modern client sends it first and falls back to initialize on any
            # error that is not a recognized modern one.
            _send({"jsonrpc": "2.0", "id": id_, "result": {
                "supportedVersions": SUPPORTED_VERSIONS,
                "capabilities": {"tools": {}},
                "instructions": SERVER_INSTRUCTIONS,
                "ttlMs": CACHE_TTL_MS,
                "cacheScope": "public",
            }})
        elif method == "initialize":
            _send({
                "jsonrpc": "2.0", "id": id_,
                "result": {
                    "protocolVersion": (
                        params.get("protocolVersion")
                        if params.get("protocolVersion") in SUPPORTED_VERSIONS
                        else PROTOCOL_LEGACY
                    ),
                    "capabilities": {"tools": {}},
                    "serverInfo": _server_info(),
                },
            })
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": id_, "result": {
                "tools": sorted(TOOL_DEFINITIONS, key=lambda t: t.get("name", "")),
                "ttlMs": CACHE_TTL_MS,
                "cacheScope": "public",
            }})
        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {}) or {}
            if tool_name != "temporal_pattern_query":
                _send({
                    "jsonrpc": "2.0", "id": id_,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps({"error": f"unknown tool: {tool_name}"})}],
                        "isError": True,
                    },
                })
                continue
            try:
                result = tool_temporal_pattern_query(tool_args)
                envelope = {"content": [{"type": "text", "text": json.dumps(result)}]}
                if isinstance(result, dict) and "error" in result:
                    envelope["isError"] = True
                _send({"jsonrpc": "2.0", "id": id_, "result": envelope})
            except Exception as e:
                _send({
                    "jsonrpc": "2.0", "id": id_,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
                        "isError": True,
                    },
                })
        else:
            _send({"jsonrpc": "2.0", "id": id_, "error": {"code": -32601, "message": f"method not found: {method}"}})


def cli():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("metric", nargs="?", default="overview", choices=list(METRICS.keys()))
    parser.add_argument("--days-back", type=int, default=60)
    args = parser.parse_args()
    print(json.dumps(tool_temporal_pattern_query({"metric": args.metric, "days_back": args.days_back}), indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "--stdio":
        cli()
    else:
        main()
