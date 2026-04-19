#!/bin/bash
# Windows-native statusline for Claude Code (via Git Bash / WSL interop).
# Companion script to hooks/statusline.ps1 which collects the actual data.
#
# The PowerShell call is expensive on Windows (~200-500ms to spin up PS),
# so this wrapper caches output to $HOME/.claude/.statusline_cache and
# only refreshes when the cache is older than MAX_AGE seconds. Claude Code
# redraws the status line frequently; without the cache, every redraw
# would visibly drag the UI.
#
# Install (Git Bash or WSL):
#   mkdir -p ~/.claude/hooks
#   cp hooks/statusline-windows.sh ~/.claude/hooks/statusline.sh
#   cp hooks/statusline.ps1        ~/.claude/hooks/statusline.ps1
#   chmod +x ~/.claude/hooks/statusline.sh
#
# Settings.json:
#   "statusLine": { "type": "command", "command": "~/.claude/hooks/statusline.sh" }

R="\033[0m" D="\033[90m"
BLU="\033[34m" GRN="\033[32m" YEL="\033[33m" CYN="\033[36m" MAG="\033[35m" WHT="\033[37m"

# Hostname resolution: env override → Windows COMPUTERNAME → POSIX hostname → fallback
HOST="${CLAUDE_HOST_LABEL:-${COMPUTERNAME:-$(hostname -s 2>/dev/null || echo WIN)}}"

CACHE="$HOME/.claude/.statusline_cache"
MAX_AGE=30  # seconds between PowerShell calls

refresh=0
if [ ! -f "$CACHE" ]; then
    refresh=1
else
    age=$(( $(date +%s) - $(date -r "$CACHE" +%s 2>/dev/null || echo 0) ))
    [ "$age" -ge "$MAX_AGE" ] && refresh=1
fi

if [ "$refresh" -eq 1 ]; then
    data=$(powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME/.claude/hooks/statusline.ps1" 2>/dev/null)
    [ -n "$data" ] && echo "$data" > "$CACHE"
fi

data=$(cat "$CACHE" 2>/dev/null)
if [ -z "$data" ]; then
    echo -e "${GRN}⬤ ${HOST}${R} ${D}· no data${R}"
    exit 0
fi

IFS='|' read -r cpu mem disk up tcp <<< "$data"

echo -e "${GRN}⬤ ${HOST}${R} ${D}·${R} ${CYN}CPU: ${cpu}%${R} ${D}·${R} ${BLU}Mem: $mem${R} ${D}·${R} ${YEL}Disk: $disk${R} ${D}·${R} ${MAG}Up: $up${R} ${D}·${R} ${WHT}TCP: $tcp${R}"
