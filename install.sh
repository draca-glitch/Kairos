#!/usr/bin/env bash
# Install or update the Kairos hooks and MCP servers into a Claude Code home.
#
# Usage: ./install.sh [CLAUDE_HOME]        default: ~/.claude
#
# Copies every file under hooks/ and mcp/ (the hooks import each other by
# path, so a partial copy breaks silently), marks them executable, and clears
# stale bytecode. Local preferences are not touched: they live in
# ~/.config/kairos/config.json (see templates/kairos-config.example.json),
# which is exactly why a reinstall cannot revert them.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
dst=${1:-$HOME/.claude}

mkdir -p "$dst/hooks" "$dst/mcp"
hooks=0; servers=0
for f in "$here"/hooks/*.py "$here"/hooks/*.sh; do
    [ -f "$f" ] || continue
    cp "$f" "$dst/hooks/"; hooks=$((hooks + 1))
done
for f in "$here"/mcp/*.py; do
    [ -f "$f" ] || continue
    cp "$f" "$dst/mcp/"; servers=$((servers + 1))
done
chmod +x "$dst"/hooks/*.sh "$dst"/hooks/*.py "$dst"/mcp/*.py
rm -rf "$dst/hooks/__pycache__" "$dst/mcp/__pycache__"

echo "kairos: installed $hooks hooks and $servers MCP servers into $dst"
echo "kairos: register them from templates/settings.json; preferences go in ~/.config/kairos/config.json"
