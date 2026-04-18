#!/bin/bash
# UserPromptSubmit hook: inject current server time so Claude has temporal
# cohesion across messages (knows how long between your replies).
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
# Detection signature: .prompt field begins with or contains the
# <task-notification> XML envelope the harness uses for automated events.
# Falls back to printing the timestamp on any jq failure (missing field,
# not-JSON input, jq absent) — silent skip is worse than spurious output.
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

date '+%Y-%m-%d %H:%M:%S %Z'
