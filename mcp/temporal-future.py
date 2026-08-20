#!/usr/bin/env python3
"""
Layer 5: MCP server exposing future-orientation queries.

Where Layer 1+2 (temporal-state, time.sh) ground 'now' and Layer 3
(temporal-staleness) audits self-knowledge against time, Layer 5 looks
*forward*: imminent deadlines, due-today tasks, upcoming obligations,
expiring memories. The kit's missing piece for "what is the agent
supposed to anticipate?".

Sources (read-only, gracefully absent):
  - $KAIROS_TASKS_DB sqlite (Mikael's task system schema with due_date)
  - $KAIROS_MEMORY_DB sqlite (Mnemos memories with valid_until)

Tools:
  temporal_future_query(horizon_days=7)
    Returns counts + curated lists of overdue / today / upcoming items.
    Horizon defines the window for "upcoming" (default one week).

  temporal_obligations_for(area, horizon_days=7)
    Filters to a single task area (e.g. "brf", "iss-seb-pdc1", "private-house").

Pure stdlib. Newline-delimited JSON-RPC 2.0 over stdin/stdout.

Registration in ~/.claude.json (mcpServers):
    "temporal-future": {
      "type": "stdio",
      "command": "python3",
      "args": ["~/.claude/mcp/temporal-future.py"]
    }
"""

import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


TASKS_DB = Path(os.environ.get("KAIROS_TASKS_DB", str(Path.home() / "work" / "tasks.db")))
MEMORY_DB = Path(os.environ.get("KAIROS_MEMORY_DB", str(Path.home() / "work" / "memory.db")))


# --- DB helpers ---


def _open_ro(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def _today_iso() -> str:
    return date.today().isoformat()


def _days_until(due_str: str | None) -> int | None:
    if not due_str:
        return None
    try:
        due = datetime.fromisoformat(due_str.split("T")[0]).date()
    except Exception:
        return None
    return (due - date.today()).days


# --- Task queries ---


def _query_tasks(area: str | None, horizon_days: int) -> dict:
    conn = _open_ro(TASKS_DB)
    if conn is None:
        return {"available": False, "path": str(TASKS_DB)}

    horizon_end = (date.today() + timedelta(days=horizon_days)).isoformat()
    today_iso = _today_iso()

    where_area = ""
    params: list = []
    if area:
        where_area = " AND area = ?"
        params.append(area)

    overdue_q = (
        "SELECT id, title, area, priority, due_date FROM tasks "
        "WHERE status='open' AND due_date IS NOT NULL AND due_date < ?" + where_area +
        " ORDER BY due_date ASC LIMIT 50"
    )
    today_q = (
        "SELECT id, title, area, priority, due_date FROM tasks "
        "WHERE status='open' AND due_date = ?" + where_area +
        " ORDER BY priority='high' DESC, priority='medium' DESC LIMIT 50"
    )
    upcoming_q = (
        "SELECT id, title, area, priority, due_date FROM tasks "
        "WHERE status='open' AND due_date > ? AND due_date <= ?" + where_area +
        " ORDER BY due_date ASC LIMIT 50"
    )

    overdue = [dict(r) for r in conn.execute(overdue_q, [today_iso] + params).fetchall()]
    due_today = [dict(r) for r in conn.execute(today_q, [today_iso] + params).fetchall()]
    upcoming = [dict(r) for r in conn.execute(upcoming_q, [today_iso, horizon_end] + params).fetchall()]

    for lst in (overdue, due_today, upcoming):
        for t in lst:
            t["days_until"] = _days_until(t.get("due_date"))

    counts = {
        "overdue": len(overdue),
        "due_today": len(due_today),
        "upcoming_in_horizon": len(upcoming),
    }

    conn.close()
    return {
        "available": True,
        "horizon_end": horizon_end,
        "overdue": overdue,
        "due_today": due_today,
        "upcoming": upcoming,
        "counts": counts,
    }


# --- Memory queries ---


def _query_expiring_memories(horizon_days: int) -> dict:
    conn = _open_ro(MEMORY_DB)
    if conn is None:
        return {"available": False, "path": str(MEMORY_DB)}

    today_iso = _today_iso()
    horizon_end = (date.today() + timedelta(days=horizon_days)).isoformat()

    try:
        rows = conn.execute(
            "SELECT id, valid_until, substr(content, 1, 120) AS preview, project, type "
            "FROM memories "
            "WHERE valid_until IS NOT NULL AND valid_until > ? AND valid_until <= ? "
            "AND status='active' "
            "ORDER BY valid_until ASC LIMIT 50",
            [today_iso, horizon_end],
        ).fetchall()
    except sqlite3.Error as e:
        conn.close()
        return {"available": False, "error": str(e)}

    items = []
    for r in rows:
        d = dict(r)
        d["days_until"] = _days_until(d.get("valid_until"))
        items.append(d)

    conn.close()
    return {
        "available": True,
        "horizon_end": horizon_end,
        "expiring": items,
        "count": len(items),
    }


# --- Highlights ---


def _build_highlights(tasks: dict, mems: dict) -> list[str]:
    """One-liner summaries the model should pay attention to."""
    out: list[str] = []
    if tasks.get("available"):
        c = tasks["counts"]
        if c["due_today"] > 0:
            out.append(f"{c['due_today']} task(s) due TODAY")
        if c["overdue"] > 0:
            high_overdue = sum(1 for t in tasks["overdue"] if t.get("priority") == "high")
            if high_overdue:
                out.append(f"{c['overdue']} overdue task(s) ({high_overdue} high-priority)")
            else:
                out.append(f"{c['overdue']} overdue task(s)")
        if c["upcoming_in_horizon"] > 0 and c["due_today"] == 0:
            # next imminent upcoming
            t = tasks["upcoming"][0]
            out.append(f"next: '{t['title'][:60]}' in {t['days_until']}d ({t['area']})")
    if mems.get("available") and mems.get("count", 0) > 0:
        out.append(f"{mems['count']} memory(ies) expiring in window")
    return out


# --- Tool entry points ---


def tool_temporal_future_query(args: dict) -> dict:
    horizon_days = max(1, min(int(args.get("horizon_days", 7) or 7), 90))
    tasks = _query_tasks(area=None, horizon_days=horizon_days)
    mems = _query_expiring_memories(horizon_days=horizon_days)
    return {
        "now": datetime.now().astimezone().isoformat(),
        "horizon_days": horizon_days,
        "tasks": tasks,
        "expiring_memories": mems,
        "highlights": _build_highlights(tasks, mems),
    }


def tool_temporal_obligations_for(args: dict) -> dict:
    area = (args.get("area") or "").strip()
    if not area:
        return {"error": "area is required"}
    horizon_days = max(1, min(int(args.get("horizon_days", 7) or 7), 90))
    tasks = _query_tasks(area=area, horizon_days=horizon_days)
    return {
        "now": datetime.now().astimezone().isoformat(),
        "area": area,
        "horizon_days": horizon_days,
        "tasks": tasks,
    }


# --- MCP protocol ---


TOOL_DEFINITIONS = [
    {
        "name": "temporal_future_query",
        "description": (
            "Layer 5 (future-orientation): return imminent obligations across the agent's "
            "task system and expiring memories. Use when the user mentions deadlines, "
            "schedules, upcoming work, planning, or any forward-looking time concept. "
            "Returns overdue tasks, tasks due today, tasks within horizon_days, expiring "
            "memories, and a 'highlights' list of one-line summaries the model should pay "
            "attention to. Default horizon is 7 days."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "horizon_days": {
                    "type": "integer",
                    "default": 7,
                    "minimum": 1,
                    "maximum": 90,
                    "description": "How far ahead to look for upcoming items (1-90).",
                },
            },
        },
    },
    {
        "name": "temporal_obligations_for",
        "description": (
            "Layer 5: filtered future-orientation query for a single task area. Use when "
            "the user is focused on one domain (e.g. 'brf', 'iss-seb-pdc1', "
            "'private-house', 'private-mom'). Returns the same overdue/today/upcoming "
            "structure as temporal_future_query but restricted to the requested area."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "area": {
                    "type": "string",
                    "description": "Task area to filter by (e.g. 'brf', 'iss-seb-pdc1').",
                },
                "horizon_days": {
                    "type": "integer",
                    "default": 7,
                    "minimum": 1,
                    "maximum": 90,
                },
            },
            "required": ["area"],
        },
    },
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
# Revisions we know by name, newest first. This list is what server/discover
# advertises -- it is documentation, not the gate. Using it AS the gate meant
# every revision we had not heard of was refused, which broke working clients
# twice: once for 2025-03-26/2025-06-18, again for 2025-11-25.
KNOWN_VERSIONS = [
    PROTOCOL_MODERN,
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    PROTOCOL_LEGACY,
]
SUPPORTED_VERSIONS = KNOWN_VERSIONS


def _is_dated_revision(version):
    parts = version.split("-")
    return (
        len(version) == 10
        and len(parts) == 3
        and [len(p) for p in parts] == [4, 2, 2]
        and all(p.isdigit() for p in parts)
    )


def protocol_supported(version):
    """Serve any dated revision between the oldest we support and the newest we
    know, named or not.

    Every revision in that range shares one tools/list and tools/call wire
    format, so the legacy path answers correctly for the ones we have no name
    for. Anything newer than PROTOCOL_MODERN is still refused: we cannot know
    what it changed, and -32022 with the known list lets the client downgrade
    to something we do understand. ISO dates sort chronologically as strings.
    """
    return bool(version) and _is_dated_revision(version) and (
        PROTOCOL_LEGACY <= version <= PROTOCOL_MODERN
    )


SERVER_NAME = "temporal-future"
SERVER_VERSION = "1.1.0"
SERVER_INSTRUCTIONS = "Query future-dated obligations and commitments held in the Mnemos memory store and the task database."
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
    sys.stderr.write("temporal-future-mcp v1.2.0 starting (version range: " + ", ".join(SUPPORTED_VERSIONS) + ")\n")
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
        if requested is not None and not protocol_supported(requested):
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
                        if protocol_supported(params.get("protocolVersion"))
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
            try:
                if tool_name == "temporal_future_query":
                    result = tool_temporal_future_query(tool_args)
                elif tool_name == "temporal_obligations_for":
                    result = tool_temporal_obligations_for(tool_args)
                else:
                    _send({
                        "jsonrpc": "2.0", "id": id_,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps({"error": f"unknown tool: {tool_name}"})}],
                            "isError": True,
                        },
                    })
                    continue
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
            _send({"jsonrpc": "2.0", "id": id_, "error": {"code": -32601, "message": f"Method not found: {method}"}})


if __name__ == "__main__":
    main()
