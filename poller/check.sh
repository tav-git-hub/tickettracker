#!/usr/bin/env bash
# Single poll of the Atleta resale availability endpoint. Invoked
# repeatedly by poller/loop.sh inside a long-running GitHub Actions job
# (see .github/workflows/monitor.yml). Compares against poller/state.json,
# notifies via ntfy on change, backs off on 429/403, and sends a daily
# heartbeat. Requires NTFY_TOPIC in the environment (repo secret).
set -euo pipefail

cd "$(dirname "$0")"

NTFY_SERVER="https://ntfy.sh"
NTFY_TOPIC="${NTFY_TOPIC:?NTFY_TOPIC environment variable not set (repo secret)}"
RESALE_URL="https://atleta.cc/e/qPULqpd5Gtfm/resale"
GRAPHQL_URL="https://atleta.cc/api/graphql"
BASE_BACKOFF_MINUTES=5
MAX_BACKOFF_MINUTES=240
STATE_FILE="state.json"
QUERY_FILE="query.json"
USER_AGENT="AtletaResaleMonitor/1.0 (personal resale-availability watch; ntfy topic ${NTFY_TOPIC})"

now_epoch=$(date -u +%s)
today=$(date -u +%F)

if [ ! -f "$STATE_FILE" ]; then
  echo '{"available":false,"backoff_level":0,"skip_until":0,"last_heartbeat_date":""}' >"$STATE_FILE"
fi

available=$(jq -r '.available' "$STATE_FILE")
backoff_level=$(jq -r '.backoff_level' "$STATE_FILE")
skip_until=$(jq -r '.skip_until' "$STATE_FILE")
last_heartbeat_date=$(jq -r '.last_heartbeat_date' "$STATE_FILE")

new_available="$available"
new_backoff_level="$backoff_level"
new_skip_until="$skip_until"

notify() {
  local title="$1" message="$2" priority="$3" click="${4:-}"
  local args=(-H "Title: $title" -H "Priority: $priority")
  if [ -n "$click" ]; then
    args+=(-H "Click: $click")
  fi
  curl -fsS "${args[@]}" -d "$message" "${NTFY_SERVER}/${NTFY_TOPIC}" >/dev/null
}

if [ "$now_epoch" -lt "$skip_until" ]; then
  echo "In backoff until epoch $skip_until (now $now_epoch); skipping this poll."
else
  http_response=$(curl -sS -w '\n%{http_code}' --max-time 15 --retry 2 --retry-delay 2 \
    -H "Content-Type: application/json" -H "Accept: */*" \
    -H "Referer: $RESALE_URL" -H "User-Agent: $USER_AGENT" \
    --data @"$QUERY_FILE" "$GRAPHQL_URL") || http_response=$'\n000'

  http_code=$(echo "$http_response" | tail -n1)
  http_body=$(echo "$http_response" | sed '$d')

  echo "HTTP $http_code"

  if [ "$http_code" = "200" ]; then
    count=$(echo "$http_body" | jq -r '.data.event.registrations_for_sale_count // empty')
    if [ -n "$count" ]; then
      if [ "$count" -gt 0 ]; then
        new_available=true
      else
        new_available=false
      fi
      new_backoff_level=0
      new_skip_until=0

      if [ "$new_available" = "true" ] && [ "$available" != "true" ]; then
        notify "Atleta resale beschikbaar" "Er zijn nu $count startbewijs(en) te koop." 5 "$RESALE_URL"
      elif [ "$new_available" = "false" ] && [ "$available" = "true" ]; then
        notify "Atleta resale niet meer beschikbaar" "Geen startbewijzen meer beschikbaar." 3 "$RESALE_URL"
      fi
    else
      echo "Unexpected response body (no registrations_for_sale_count field): $http_body"
    fi
  elif [ "$http_code" = "429" ] || [ "$http_code" = "403" ]; then
    new_backoff_level=$((backoff_level + 1))
    backoff_minutes=$((BASE_BACKOFF_MINUTES * (1 << new_backoff_level)))
    if [ "$backoff_minutes" -gt "$MAX_BACKOFF_MINUTES" ]; then
      backoff_minutes=$MAX_BACKOFF_MINUTES
    fi
    new_skip_until=$((now_epoch + backoff_minutes * 60))
    if [ "$backoff_level" = "0" ]; then
      notify "Atleta monitor: backoff geactiveerd" "HTTP $http_code ontvangen. Poll-interval wordt tijdelijk verhoogd naar ${backoff_minutes} min." 4 ""
    fi
  else
    echo "Non-200/429/403 response ($http_code); leaving state unchanged, retrying next scheduled run."
  fi
fi

if [ "$last_heartbeat_date" != "$today" ]; then
  notify "Atleta monitor: heartbeat" "De poller draait nog. Laatste bekende status: available=$new_available." 1 ""
  last_heartbeat_date="$today"
fi

jq -n --argjson available "$new_available" \
  --argjson backoff_level "$new_backoff_level" \
  --argjson skip_until "$new_skip_until" \
  --arg last_heartbeat_date "$last_heartbeat_date" \
  '{available: $available, backoff_level: $backoff_level, skip_until: $skip_until, last_heartbeat_date: $last_heartbeat_date}' \
  >"$STATE_FILE"

echo "State: $(cat "$STATE_FILE")"
