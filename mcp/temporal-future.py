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


def _read_msg():
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        return json.loads(line)
    except Exception:
        return None


def _send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    sys.stderr.write("temporal-future-mcp v1.0 starting\n")
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

        if method == "initialize":
            _send({
                "jsonrpc": "2.0", "id": id_,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "temporal-future", "version": "1.0.0"},
                },
            })
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": id_, "result": {"tools": TOOL_DEFINITIONS}})
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
