"""The stdio MCP servers must serve both protocol eras.

2026-07-28 removed the initialize handshake: a modern client declares its
protocol version in per-request `_meta`, servers MUST implement
`server/discover`, and every result carries `resultType`. A legacy client
still opens with `initialize` and never announces a version per request.

The spec's compatibility matrix has exactly one server kind that works with
both client eras -- dual-era -- so these tests pin both paths at once. The
legacy half matters most: it is what the currently deployed clients speak,
and a regression there takes the temporal layer down in three harnesses.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

MCP_DIR = Path(__file__).resolve().parent.parent / "mcp"
SERVERS = ["temporal-pattern", "temporal-staleness", "temporal-future"]
MODERN = "2026-07-28"
LEGACY = "2024-11-05"
SERVER_INFO_KEY = "io.modelcontextprotocol/serverInfo"
PROTOCOL_KEY = "io.modelcontextprotocol/protocolVersion"


def modern_meta(version=MODERN):
    return {
        "_meta": {
            PROTOCOL_KEY: version,
            "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
        }
    }


def talk(server, messages):
    """Feed newline-delimited JSON-RPC to a server, return parsed replies by id."""
    proc = subprocess.run(
        [sys.executable, str(MCP_DIR / f"{server}.py")],
        input="\n".join(json.dumps(m) for m in messages) + "\n",
        capture_output=True,
        text=True,
        timeout=120,
    )
    replies = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return {r.get("id"): r for r in replies}


@pytest.fixture(scope="module", params=SERVERS)
def replies(request):
    """One process per server, exercised across both eras."""
    server = request.param
    out = talk(server, [
        {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": modern_meta()},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": modern_meta()},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 4, "method": "initialize",
         "params": {"protocolVersion": LEGACY, "capabilities": {}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/list",
         "params": {"_meta": {PROTOCOL_KEY: "1900-01-01"}}},
    ])
    return server, out


def test_discover_is_implemented(replies):
    server, out = replies
    result = out[1]["result"]
    assert MODERN in result["supportedVersions"]
    assert LEGACY in result["supportedVersions"], "legacy clients must stay served"
    assert result["capabilities"]["tools"] == {}
    assert result["_meta"][SERVER_INFO_KEY]["name"] == server
    assert result["instructions"]


def test_every_modern_result_declares_completion(replies):
    _server, out = replies
    assert out[1]["result"]["resultType"] == "complete"
    assert out[2]["result"]["resultType"] == "complete"


def test_list_results_are_cacheable(replies):
    _server, out = replies
    result = out[2]["result"]
    assert result["ttlMs"] > 0
    assert result["cacheScope"] in ("public", "private")


def test_tools_are_ordered_deterministically(replies):
    _server, out = replies
    names = [t["name"] for t in out[2]["result"]["tools"]]
    assert names and names == sorted(names)


def test_legacy_request_without_meta_is_not_rejected(replies):
    """Absence of a declared version is the legacy era, never a mismatch."""
    _server, out = replies
    assert "error" not in out[3]
    assert out[3]["result"]["tools"] == out[2]["result"]["tools"]


def test_initialize_still_negotiates_and_stays_legacy_shaped(replies):
    _server, out = replies
    result = out[4]["result"]
    assert result["protocolVersion"] == LEGACY
    assert result["serverInfo"]["version"] == "1.1.0"
    # A legacy client is the only thing that sees this result; leave it alone.
    assert "resultType" not in result
    assert "_meta" not in result


def test_unsupported_version_is_refused_with_a_retry_path(replies):
    _server, out = replies
    error = out[5]["error"]
    assert error["code"] == -32022
    assert error["data"]["requested"] == "1900-01-01"
    # `supported` is what lets the client pick a version and retry.
    assert MODERN in error["data"]["supported"]


@pytest.mark.parametrize("server,call", [
    ("temporal-pattern",
     {"name": "temporal_pattern_query", "arguments": {"metric": "overview", "days_back": 7}}),
    ("temporal-future",
     {"name": "temporal_future_query", "arguments": {}}),
])
def test_tool_calls_still_work_under_the_modern_envelope(server, call):
    params = dict(call)
    params.update(modern_meta())
    out = talk(server, [{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}])
    result = out[1]["result"]
    assert result["resultType"] == "complete"
    assert not result.get("isError"), result
    assert json.loads(result["content"][0]["text"])
