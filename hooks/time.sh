#!/bin/bash
# UserPromptSubmit hook: inject current server time so Claude has temporal
# cohesion across messages (knows how long between your replies).
#
# v2 (2026-04-28): emit time on every real prompt, but include the date
# only when it differs from the previous fire in the same session. Saves
# tokens while keeping date awareness on session start, post-midnight,
# and resumed-next-day cases.
#
# Filters out automated task-notification events. The Claude Code harness
# routes background-task notifications (Bash completion, Monitor stream
# events) through the same UserPromptSubmit hook pipeline as real user
# prompts, with no env var or payload field to distinguish the two
# (verified via docs.claude.com 2026-04-18). Without this filter, every
# monitor event spams "UserPromptSubmit hook success: <timestamp>"
# prefixes, drowning real user prompts in noise during long-running
# background work.
#
# Detection signature: .prompt field contains the <task-notification> XML
# envelope the harness uses for automated events. Falls back to printing
# the timestamp on any jq failure (missing field, not-JSON input, jq
# absent), since silent skip is worse than spurious output.
#
# Marker file: $TMPDIR/claude-kit-time/<session_id>.last-date
# Per-session isolation via $CLAUDE_SESSION_ID. Cleared on reboot (tmpfs).
#
# Usage in settings.json:
#   "UserPromptSubmit": [{
#     "hooks": [{
#       "type": "command",
#       "command": "~/.claude/hooks/time.sh",
#       "timeout": 2000
#     }]
#   }]

PAYLOAD=$(cat)
PROMPT_TEXT=$(echo "$PAYLOAD" | jq -r '.prompt // empty' 2>/dev/null)

case "$PROMPT_TEXT" in
    *"<task-notification>"*) exit 0 ;;
esac

SESSION="${CLAUDE_SESSION_ID:-default}"
MARKER_DIR="${TMPDIR:-/tmp}/claude-kit-time"
MARKER="$MARKER_DIR/${SESSION}.last-date"
mkdir -p "$MARKER_DIR" 2>/dev/null

TODAY=$(date '+%Y-%m-%d')
LAST_DATE=$(cat "$MARKER" 2>/dev/null || echo "")

if [ "$TODAY" != "$LAST_DATE" ]; then
    # First fire of session, or date crossed since last fire: full datetime.
    date '+%Y-%m-%d %H:%M:%S %Z'
    echo "$TODAY" > "$MARKER"
else
    # Same date as previous fire: time only.
    date '+%H:%M:%S %Z'
fi
