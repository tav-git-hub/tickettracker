#!/usr/bin/env bash
# Long-running poll loop: calls check.sh every CHECK_INTERVAL_SECONDS and
# commits+pushes poller/state.json whenever it changes. Runs inside a
# single GitHub Actions job (see .github/workflows/monitor.yml), which
# restarts this on a cron cadence well before the job's own timeout, so
# coverage is continuous with only a few seconds' gap at each restart.
set -uo pipefail

cd "$(dirname "$0")"

# Fail fast on a config error instead of looping for hours printing the
# same error every 30s (this is exactly what happened before this guard
# existed: NTFY_TOPIC was never set, and the loop burned a full ~4h45m of
# Actions minutes per restart, 571 failed iterations, doing nothing).
: "${NTFY_TOPIC:?NTFY_TOPIC environment variable not set (add it as a repo secret) -- refusing to start the loop}"

CHECK_INTERVAL_SECONDS=30
# Stay comfortably under the job's timeout-minutes (leaves room for
# checkout/setup overhead and a graceful final commit+push).
LOOP_BUDGET_SECONDS="${LOOP_BUDGET_SECONDS:-17100}" # 4h45m

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

commit_if_changed() {
  if [ -n "$(git status --porcelain -- state.json)" ]; then
    git add state.json
    git commit -q -m "Update poller state [skip ci]"
    if ! git push -q; then
      echo "Push failed, retrying after rebase..."
      git pull -q --rebase && git push -q || echo "WARN: push still failing, will retry next iteration"
    fi
  fi
}

start_epoch=$(date -u +%s)
iteration=0

while true; do
  iteration=$((iteration + 1))
  now_epoch=$(date -u +%s)
  elapsed=$((now_epoch - start_epoch))
  if [ "$elapsed" -ge "$LOOP_BUDGET_SECONDS" ]; then
    echo "Loop budget reached (${elapsed}s, iteration $iteration); exiting for scheduled restart."
    break
  fi

  bash check.sh || echo "check.sh exited non-zero (iteration $iteration), continuing loop"
  commit_if_changed

  sleep "$CHECK_INTERVAL_SECONDS"
done
