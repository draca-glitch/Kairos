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
    Horizon defines the window for "upcoming" (default one week). Counts are
    true totals; each list holds at most 50 rows.

  temporal_obligations_for(area, horizon_days=7)
    Filters to one task area or a family of them. `area` is an exact area
    name, or a prefix of any hyphen-separated part of one: with areas
    "work-site-a" and "work-site-b", both "work" and "site" select the two.
    An area that matches nothing is an error that lists the known areas.

Memories: `expiring` are active memories whose valid_until falls today or
later inside the horizon. `expired_active` counts active memories already
past valid_until and lists the newest few. Mnemos closes a superseded memory
by setting valid_until to the day it was replaced and linking it to its
successor, so a memory with an outgoing evolves / superseded_by link is
history, not an obligation, and appears in neither list.

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




def _resolve_dbs() -> tuple[Path, Path]:
    """Both DB paths come from temporal_lib's shared resolver (env, then
    ~/.config/kairos/config.json, then MNEMOS_DB, then the conventional
    locations). The library sits in ../hooks in both the repo and the
    installed ~/.claude layout; a standalone deployment without it falls
    back to env-or-default."""
    for candidate in (Path(__file__).resolve().parent.parent / "hooks",
                      Path.home() / ".claude" / "hooks"):
        if (candidate / "temporal_lib.py").exists():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            try:
                from temporal_lib import memory_db_path, tasks_db_path
                return tasks_db_path(), memory_db_path()
            except Exception:
                break
    work = Path.home() / "work"

    def conventional(name):
        # ~/work/db is the convention; ~/work covers a store not moved there yet.
        old = work / name
        return old if old.exists() and not (work / "db" / name).exists() else work / "db" / name
    return (Path(os.environ.get("KAIROS_TASKS_DB") or conventional("tasks.db")),
            Path(os.environ.get("KAIROS_MEMORY_DB") or conventional("memory.db")))


TASKS_DB, MEMORY_DB = _resolve_dbs()


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


LIST_LIMIT = 50

# A due_date that is not a date (an empty string, free text) compares as a
# string and would otherwise sit in "overdue" forever.
_IS_DATE = " AND due_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*'"


def _known_areas() -> list[str] | None:
    """Every area the task table uses, or None when the DB is unavailable."""
    conn = _open_ro(TASKS_DB)
    if conn is None:
        return None
    try:
        rows = conn.execute(
            "SELECT DISTINCT area FROM tasks WHERE area IS NOT NULL AND area != '' ORDER BY area"
        ).fetchall()
        return [r[0] for r in rows]
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def match_areas(query: str, known: list[str]) -> list[str]:
    """Areas selected by `query`: the exact area when one exists, otherwise
    every area in which the query is a prefix starting at a hyphen-separated
    part ("site" selects "work-site-a"; "ork" selects nothing)."""
    q = query.strip().lower()
    if not q:
        return []
    exact = [a for a in known if a.lower() == q]
    if exact:
        return exact
    matched = []
    for area in known:
        parts = area.lower().split("-")
        if any("-".join(parts[i:]).startswith(q) for i in range(len(parts))):
            matched.append(area)
    return matched


def _query_tasks(area: str | list[str] | None, horizon_days: int) -> dict:
    conn = _open_ro(TASKS_DB)
    if conn is None:
        return {"available": False, "path": str(TASKS_DB)}

    horizon_end = (date.today() + timedelta(days=horizon_days)).isoformat()
    today_iso = _today_iso()

    where_area = ""
    params: list = []
    if area:
        areas = [area] if isinstance(area, str) else list(area)
        where_area = " AND area IN (" + ",".join("?" * len(areas)) + ")"
        params.extend(areas)

    cols = "SELECT id, title, area, priority, due_date FROM tasks "
    overdue_w = "WHERE status='open' AND due_date IS NOT NULL AND due_date < ?" + _IS_DATE + where_area
    today_w = "WHERE status='open' AND due_date = ?" + where_area
    upcoming_w = "WHERE status='open' AND due_date > ? AND due_date <= ?" + _IS_DATE + where_area
    limit = f" LIMIT {LIST_LIMIT}"

    def rows(where: str, order: str, args: list) -> list[dict]:
        return [dict(r) for r in conn.execute(cols + where + order + limit, args).fetchall()]

    def count(where: str, args: list) -> int:
        return conn.execute("SELECT COUNT(*) FROM tasks " + where, args).fetchone()[0]

    try:
        # Past the cap, keep the most recently missed and drop the longest
        # dead; the list itself stays oldest first.
        overdue = rows(overdue_w, " ORDER BY due_date DESC", [today_iso] + params)
        overdue.reverse()
        due_today = rows(today_w, " ORDER BY priority='high' DESC, priority='medium' DESC",
                         [today_iso] + params)
        upcoming = rows(upcoming_w, " ORDER BY due_date ASC", [today_iso, horizon_end] + params)
        # Counted separately: the lists stop at LIST_LIMIT, the counts must not.
        counts = {
            "overdue": count(overdue_w, [today_iso] + params),
            "overdue_high": count(overdue_w + " AND priority='high'", [today_iso] + params),
            "due_today": count(today_w, [today_iso] + params),
            "upcoming_in_horizon": count(upcoming_w, [today_iso, horizon_end] + params),
        }
    except sqlite3.Error as e:
        return {"available": False, "error": str(e)}
    finally:
        conn.close()

    for lst in (overdue, due_today, upcoming):
        for t in lst:
            t["days_until"] = _days_until(t.get("due_date"))

    return {
        "available": True,
        "horizon_end": horizon_end,
        "overdue": overdue,
        "due_today": due_today,
        "upcoming": upcoming,
        "counts": counts,
        "list_limit": LIST_LIMIT,
    }


# --- Memory queries ---


EXPIRED_ACTIVE_SHOWN = 5

# Outgoing link types by which Mnemos marks a memory as replaced by a newer
# one (older -> newer). Such a memory got valid_until set on the day it was
# superseded; that date records history, it is not a deadline.
SUPERSEDED_LINKS = ("evolves", "superseded_by")


def _query_expiring_memories(horizon_days: int) -> dict:
    conn = _open_ro(MEMORY_DB)
    if conn is None:
        return {"available": False, "path": str(MEMORY_DB)}

    today_iso = _today_iso()
    horizon_end = (date.today() + timedelta(days=horizon_days)).isoformat()

    cols = "SELECT id, valid_until, substr(content, 1, 120) AS preview, project, type FROM memories m "
    day = "substr(m.valid_until, 1, 10)"
    live = "WHERE m.valid_until IS NOT NULL AND m.status='active'"
    try:
        has_links = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_links'"
        ).fetchone() is not None
        if has_links:
            marks = ",".join("?" * len(SUPERSEDED_LINKS))
            live += (" AND NOT EXISTS (SELECT 1 FROM memory_links l WHERE l.source_id = m.id"
                     f" AND l.relation_type IN ({marks}))")
        link_args = list(SUPERSEDED_LINKS) if has_links else []

        window_w = f"{live} AND {day} >= ? AND {day} <= ?"
        window_args = link_args + [today_iso, horizon_end]
        rows = conn.execute(cols + window_w + f" ORDER BY {day} ASC LIMIT {LIST_LIMIT}",
                            window_args).fetchall()
        count = conn.execute("SELECT COUNT(*) FROM memories m " + window_w, window_args).fetchone()[0]

        expired_w = f"{live} AND {day} < ?"
        expired_args = link_args + [today_iso]
        expired_rows = conn.execute(
            cols + expired_w + f" ORDER BY {day} DESC, m.id DESC LIMIT {EXPIRED_ACTIVE_SHOWN}",
            expired_args).fetchall()
        expired_count = conn.execute("SELECT COUNT(*) FROM memories m " + expired_w,
                                     expired_args).fetchone()[0]
    except sqlite3.Error as e:
        return {"available": False, "error": str(e)}
    finally:
        conn.close()

    def with_days(found) -> list[dict]:
        items = []
        for r in found:
            d = dict(r)
            d["days_until"] = _days_until(d.get("valid_until"))
            items.append(d)
        return items

    return {
        "available": True,
        "horizon_end": horizon_end,
        "expiring": with_days(rows),
        "count": count,
        "expired_active": {
            "count": expired_count,
            "newest": with_days(expired_rows),
            "note": "active memories already past valid_until; retire or extend them",
        },
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
            high_overdue = c.get("overdue_high",
                                 sum(1 for t in tasks["overdue"] if t.get("priority") == "high"))
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


def _clamp_horizon(value) -> int:
    try:
        days = int(value or 7)
    except (TypeError, ValueError):
        days = 7
    return max(1, min(days, 90))


def tool_temporal_future_query(args: dict) -> dict:
    horizon_days = _clamp_horizon(args.get("horizon_days", 7))
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
    area = str(args.get("area") or "").strip()
    if not area:
        return {"error": "area is required"}
    horizon_days = _clamp_horizon(args.get("horizon_days", 7))
    known = _known_areas()
    if known is None:
        matched = [area]
    else:
        matched = match_areas(area, known)
        if not matched:
            # Zero tasks for a misspelt area reads as "nothing is due".
            return {
                "error": f"no task area matches '{area}'. Known areas: {', '.join(known) or '(none)'}",
                "area": area,
                "known_areas": known,
            }
    tasks = _query_tasks(area=matched, horizon_days=horizon_days)
    return {
        "now": datetime.now().astimezone().isoformat(),
        "area": area,
        "matched_areas": matched,
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
            "attention to. Default horizon is 7 days. 'counts' are true totals; each task "
            "list holds at most 50 rows. expiring_memories.expiring are active memories "
            "whose valid_until falls today or later within the horizon; "
            "expiring_memories.expired_active gives the count of active memories already "
            "past valid_until plus the newest few. Memories superseded by a newer one are "
            "in neither."
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
            "Layer 5: future-orientation query filtered to one task area or a family of "
            "areas. Use when the user is focused on one domain. 'area' is an exact area "
            "name, or a prefix of any hyphen-separated part of one (with areas "
            "'work-site-a' and 'work-site-b', both 'work' and 'site' select the two). "
            "Returns the same overdue/today/upcoming structure as temporal_future_query "
            "restricted to the matched areas, listed in 'matched_areas'. An area that "
            "matches nothing returns an error listing the known areas, never an empty result."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "area": {
                    "type": "string",
                    "description": "Exact task area, or a prefix of one of its hyphen-separated parts.",
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
SERVER_VERSION = "1.2.1"
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
    """Next JSON-RPC message, or None at end of input. A blank line, invalid
    JSON or a payload that is not an object is skipped: only EOF ends the
    server, since one stray line must not take the tools away mid-session."""
    while True:
        line = sys.stdin.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if isinstance(msg, dict):
            return msg


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
    sys.stderr.write(f"{SERVER_NAME}-mcp v{SERVER_VERSION} starting (version range: " + ", ".join(SUPPORTED_VERSIONS) + ")\n")
    sys.stderr.flush()
    while True:
        msg = _read_msg()
        if msg is None:
            break
        method = msg.get("method", "")
        id_ = msg.get("id")
        params = msg.get("params")
        if not isinstance(params, dict):
            params = {}

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
        elif method == "ping":
            _send({"jsonrpc": "2.0", "id": id_, "result": {}})
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": id_, "result": {
                "tools": sorted(TOOL_DEFINITIONS, key=lambda t: t.get("name", "")),
                "ttlMs": CACHE_TTL_MS,
                "cacheScope": "public",
            }})
        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments")
            if not isinstance(tool_args, dict):
                tool_args = {}
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
