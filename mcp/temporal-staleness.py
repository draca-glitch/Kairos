#!/usr/bin/env python3
"""
Layer 3: MCP server exposing temporal_staleness_audit.

Where temporal-state.py tells Claude what time it is, and temporal-pattern.py
tells Claude what the user's rhythm looks like, this one tells Claude
"given current date and topic, is my answer likely to be stale?".

The model's training cutoff is fixed; the world moves forward. Without an
explicit check, Claude over-trusts knowledge from 4+ months ago in domains
where 4 months is forever (security CVEs, news, software libraries) and
under-trusts in domains where 4 months is nothing (mathematics, classics,
historical events).

Tool: temporal_staleness_audit
  topic:  the subject the answer would address (free text)
  domain: optional category. If omitted, returns analysis for the most
          conservative reasonable interpretation.

Returns:
  risk:               low | medium | high
  days_since_cutoff:  integer
  half_life_days:     domain volatility in days (null for ageless domains)
  rationale:          one-sentence why
  suggestion:         proceed | qualify | web_search

Pure stdlib. Newline-delimited JSON-RPC 2.0 over stdin/stdout.

Registration in ~/.claude.json (mcpServers):
    "temporal-staleness": {
      "type": "stdio",
      "command": "python3",
      "args": ["~/.claude/mcp/temporal-staleness.py"]
    }
"""

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path


def _import_keyword_map():
    """Reuse hooks/keywords.KEYWORD_TO_DOMAIN when reachable.

    Falls through to the inline copy below if the hooks/ directory is not
    on disk in any expected location (standalone MCP distribution).
    """
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "hooks",
        Path.home() / ".claude" / "hooks",
        Path(os.environ.get("CLAUDE_KIT_HOOKS_DIR", "")),
    ]
    for c in candidates:
        if c and (c / "keywords.py").exists():
            if str(c) not in sys.path:
                sys.path.insert(0, str(c))
            try:
                from keywords import KEYWORD_TO_DOMAIN as _shared
                return _shared
            except Exception:
                continue
    return None


_SHARED_KEYWORD_MAP = _import_keyword_map()


CUTOFF_STR = os.environ.get("CLAUDE_TRAINING_CUTOFF", "2026-01-01")
try:
    CUTOFF_DATE = datetime.strptime(CUTOFF_STR, "%Y-%m-%d").date()
except Exception:
    CUTOFF_DATE = date(2026, 1, 1)


# Domain volatility: half-life in days. None = ageless (knowledge does
# not decay materially with time). Values are deliberately conservative,
# Claude should err on the side of qualifying rather than overclaiming.
DOMAIN_HALF_LIFE = {
    "general": None,
    "concepts": None,
    "math": None,
    "mathematics": None,
    "history": None,
    "classics": None,
    "philosophy": None,
    "literature": None,
    "biology-basics": None,

    "tech": 90,
    "software": 90,
    "libraries": 90,
    "framework": 90,
    "api": 90,
    "programming": 120,

    "ai": 60,
    "llm": 60,
    "ml": 90,

    "medical": 180,
    "legal": 180,
    "regulation": 180,
    "policy": 180,

    "security": 30,
    "cve": 30,
    "exploit": 30,
    "vulnerability": 30,

    "politics": 7,
    "news": 7,
    "current-events": 7,
    "sports": 7,
    "weather": 1,

    "pricing": 14,
    "markets": 14,
    "stocks": 7,
    "crypto": 3,
}


def normalize_domain(domain: str | None) -> str:
    if not domain:
        return ""
    return domain.strip().lower().replace("_", "-")


def infer_domain_from_topic(topic: str) -> str:
    """Best-effort domain inference from topic keywords.

    Scoring rule: collect ALL keyword matches, then pick the domain with the
    SHORTEST half-life (most acute volatility). Ageless domains (half_life=None)
    only win when no time-sensitive match exists. Falls back to ''.
    """
    t = (topic or "").lower()
    keyword_map = _SHARED_KEYWORD_MAP if _SHARED_KEYWORD_MAP is not None else [
        # Inline fallback used only when hooks/keywords.py is unreachable.
        # Kept in lockstep with hooks/keywords.py:KEYWORD_TO_DOMAIN.
        ("cve", "security"), ("vulnerab", "security"), ("exploit", "security"),
        ("zero-day", "security"), ("0day", "security"),
        ("price", "pricing"), ("pricing", "pricing"), ("cost", "pricing"),
        ("stock", "stocks"), ("market", "markets"),
        ("crypto", "crypto"), ("bitcoin", "crypto"),
        ("election", "politics"), ("news", "news"),
        ("law", "legal"), ("statute", "legal"), ("regulation", "regulation"),
        ("medical", "medical"), ("treatment", "medical"), ("diagnos", "medical"), ("drug", "medical"),
        ("gpt-", "ai"), ("claude", "ai"), ("llm", "llm"), ("model", "ai"),
        ("library", "libraries"), ("package", "libraries"), ("framework", "framework"),
        ("api", "api"), ("software", "software"), ("python", "software"), ("node", "software"),
        ("react", "framework"),
        ("history", "history"), ("theorem", "math"), ("proof", "math"), ("equation", "math"),
    ]
    matches = [dom for needle, dom in keyword_map if needle in t]
    if not matches:
        return ""

    def acuity(dom: str) -> float:
        hl = DOMAIN_HALF_LIFE.get(dom)
        return float("inf") if hl is None else float(hl)

    return min(matches, key=acuity)


def days_since_cutoff() -> int:
    today = date.today()
    return max(0, (today - CUTOFF_DATE).days)


def assess(topic: str, domain_in: str | None) -> dict:
    domain = normalize_domain(domain_in) or infer_domain_from_topic(topic)
    days = days_since_cutoff()

    if not domain:
        # Unknown domain → treat conservatively as medium tech-pace.
        domain = "general-unknown"
        half_life = 60
    elif domain in DOMAIN_HALF_LIFE:
        half_life = DOMAIN_HALF_LIFE[domain]
    else:
        half_life = 60  # unrecognized → conservative default

    if half_life is None:
        risk = "low"
        rationale = f"Domain '{domain}' is ageless: training cutoff does not materially affect this answer."
        suggestion = "proceed"
    else:
        ratio = days / half_life if half_life > 0 else float("inf")
        if ratio < 0.5:
            risk = "low"
            suggestion = "proceed"
            rationale = (
                f"{days}d since training cutoff vs {half_life}d domain half-life "
                f"(ratio {ratio:.2f}), well within freshness window."
            )
        elif ratio < 2.0:
            risk = "medium"
            suggestion = "qualify"
            rationale = (
                f"{days}d since training cutoff vs {half_life}d domain half-life "
                f"(ratio {ratio:.2f}), qualify answer with 'as of training cutoff' and "
                f"note possible drift."
            )
        else:
            risk = "high"
            suggestion = "web_search"
            rationale = (
                f"{days}d since training cutoff vs {half_life}d domain half-life "
                f"(ratio {ratio:.2f}), likely stale; verify with web search before answering."
            )

    return {
        "topic": topic,
        "domain": domain,
        "domain_source": "explicit" if domain_in else "inferred-or-default",
        "days_since_cutoff": days,
        "cutoff_date": CUTOFF_DATE.isoformat(),
        "half_life_days": half_life,
        "risk": risk,
        "rationale": rationale,
        "suggestion": suggestion,
    }


def tool_temporal_staleness_audit(args: dict) -> dict:
    topic = (args.get("topic") or "").strip()
    if not topic:
        return {"error": "topic is required"}
    domain = args.get("domain")
    return assess(topic, domain)


# --- MCP protocol ---


TOOL_DEFINITIONS = [
    {
        "name": "temporal_staleness_audit",
        "description": (
            "Assess whether an answer about a given topic is likely to be stale due to time elapsed "
            "since the model's training cutoff. Returns risk level (low/medium/high), days since "
            "cutoff, domain half-life, rationale, and a procedural suggestion (proceed / qualify / "
            "web_search). Domains are categorized by volatility: news/sports are 7-day half-life, "
            "security/CVE 30-day, tech/software 90-day, medical/legal 180-day, math/history are "
            "ageless. If domain is omitted, the tool infers one from the topic text."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The subject the answer would address.",
                },
                "domain": {
                    "type": "string",
                    "description": "Optional category override. One of: general, tech, software, libraries, api, ai, llm, medical, legal, security, politics, news, pricing, markets, crypto, math, history, etc.",
                },
            },
            "required": ["topic"],
        },
    }
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
    sys.stderr.write("temporal-staleness-mcp v1.0 starting\n")
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
                    "serverInfo": {"name": "temporal-staleness", "version": "1.0.0"},
                },
            })
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": id_, "result": {"tools": TOOL_DEFINITIONS}})
        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {}) or {}
            if tool_name != "temporal_staleness_audit":
                _send({
                    "jsonrpc": "2.0", "id": id_,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps({"error": f"unknown tool: {tool_name}"})}],
                        "isError": True,
                    },
                })
                continue
            try:
                result = tool_temporal_staleness_audit(tool_args)
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
