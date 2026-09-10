#!/usr/bin/env python3
"""
Long-running poll loop that drives a real (headless) browser instead of
raw HTTP requests, clicking the page's own refresh button every ~30s.

Rationale: the raw-curl poller (check.sh/loop.sh) sometimes gets 429'd,
and it sends a self-identifying User-Agent ("AtletaResaleMonitor/1.0...")
that a WAF/bot-detector can trivially fingerprint. A real Chromium session
clicking the actual UI button looks like normal browser traffic (default
Chrome UA, real TLS/HTTP2 fingerprint, JS execution) -- this may avoid
whatever is triggering the blocking. Uses one browser session for the
whole job run (not one per check) to keep cost low.

Same state.json schema and git commit-back behavior as loop.sh, same
ntfy notifications, same backoff-on-429 logic -- only the transport
(browser click vs curl) differs.
"""
import json
import os
import re
import subprocess
import sys
import time

RESALE_URL = "https://atleta.cc/e/qPULqpd5Gtfm/resale"
TARGET_OPERATION = "GetRegistrationsForSale"
NTFY_SERVER = "https://ntfy.sh"
CHECK_INTERVAL_SECONDS = 30
BASE_BACKOFF_MINUTES = 5
MAX_BACKOFF_MINUTES = 240
RELOAD_EVERY_SECONDS = 1800  # refresh the page periodically on long runs
STATE_FILE = os.path.join(os.path.dirname(__file__), os.environ.get("STATE_FILE_NAME", "state.json"))


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"available": False, "backoff_level": 0, "skip_until": 0, "last_heartbeat_date": ""}
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def commit_state_if_changed():
    state_name = os.path.basename(STATE_FILE)
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", state_name],
        cwd=os.path.dirname(__file__),
        capture_output=True,
        text=True,
    )
    if not result.stdout.strip():
        return
    cwd = os.path.dirname(__file__)
    subprocess.run(["git", "add", state_name], cwd=cwd, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "Update poller state [skip ci]"], cwd=cwd, check=True)
    push = subprocess.run(["git", "push", "-q"], cwd=cwd)
    if push.returncode != 0:
        print("Push failed, retrying after rebase...")
        subprocess.run(["git", "pull", "-q", "--rebase"], cwd=cwd)
        retry = subprocess.run(["git", "push", "-q"], cwd=cwd)
        if retry.returncode != 0:
            print("WARN: push still failing, will retry next iteration")


def notify(title, message, priority, click=""):
    ntfy_topic = os.environ["NTFY_TOPIC"]
    args = ["curl", "-fsS", "-H", f"Title: {title}", "-H", f"Priority: {priority}"]
    if click:
        args += ["-H", f"Click: {click}"]
    args += ["-d", message, f"{NTFY_SERVER}/{ntfy_topic}"]
    subprocess.run(args, capture_output=True)


def dismiss_cookie_banner(page):
    for text in ("Accept", "Reject"):
        try:
            page.locator(f"text={text}").first.click(timeout=2000)
            print(f"Dismissed cookie banner via '{text}'")
            return
        except Exception:
            continue


def main():
    from playwright.sync_api import sync_playwright

    if "NTFY_TOPIC" not in os.environ:
        print("NTFY_TOPIC environment variable not set -- refusing to start", file=sys.stderr)
        sys.exit(1)

    loop_budget_seconds = int(os.environ.get("LOOP_BUDGET_SECONDS", "17100"))

    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=os.path.dirname(__file__))
    subprocess.run(
        ["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"],
        cwd=os.path.dirname(__file__),
    )

    captured = []

    def on_request_finished(request):
        if request.resource_type not in ("xhr", "fetch"):
            return
        if TARGET_OPERATION not in (request.post_data or ""):
            return
        try:
            response = request.response()
        except Exception:
            return
        if response is None:
            return
        entry = {"status": response.status, "ts": time.monotonic()}
        try:
            entry["body"] = response.text()
        except Exception as e:
            entry["body"] = None
            entry["error"] = str(e)
        captured.append(entry)

    state = load_state()
    start = time.monotonic()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.on("requestfinished", on_request_finished)

        print(f"Loading {RESALE_URL}")
        page.goto(RESALE_URL, wait_until="networkidle", timeout=30000)
        dismiss_cookie_banner(page)
        time.sleep(1)

        last_reload = time.monotonic()
        iteration = 0

        while True:
            iteration += 1
            elapsed = time.monotonic() - start
            if elapsed >= loop_budget_seconds:
                print(f"Loop budget reached ({elapsed:.0f}s, iteration {iteration}); exiting for scheduled restart.")
                break

            now_epoch = int(time.time())
            if now_epoch < state["skip_until"]:
                print(f"In backoff until epoch {state['skip_until']} (now {now_epoch}); skipping this poll.")
            else:
                if time.monotonic() - last_reload > RELOAD_EVERY_SECONDS:
                    print("Periodic reload...")
                    page.reload(wait_until="networkidle", timeout=30000)
                    dismiss_cookie_banner(page)
                    last_reload = time.monotonic()

                before = len(captured)
                clicked = False
                try:
                    page.locator(r"text=/Refreshed at \d{2}:\d{2}:\d{2}/").first.click(timeout=5000)
                    clicked = True
                except Exception as e:
                    print(f"Click failed: {e}")

                if clicked:
                    deadline = time.monotonic() + 10
                    while len(captured) == before and time.monotonic() < deadline:
                        time.sleep(0.2)

                if len(captured) > before:
                    entry = captured[-1]
                    status = entry["status"]
                    print(f"HTTP {status}")
                    if status == 200 and entry.get("body"):
                        try:
                            data = json.loads(entry["body"])
                            count = data["data"]["event"]["registrations_for_sale_count"]
                        except Exception as e:
                            count = None
                            print(f"Could not parse response: {e}")
                        if count is not None:
                            new_available = count > 0
                            was_available = state["available"]
                            state["backoff_level"] = 0
                            state["skip_until"] = 0
                            state["available"] = new_available
                            if new_available and not was_available:
                                notify(
                                    "Atleta resale beschikbaar",
                                    f"Er zijn nu {count} startbewijs(en) te koop.",
                                    5,
                                    RESALE_URL,
                                )
                            elif was_available and not new_available:
                                notify(
                                    "Atleta resale niet meer beschikbaar",
                                    "Geen startbewijzen meer beschikbaar.",
                                    3,
                                    RESALE_URL,
                                )
                    elif status in (429, 403):
                        old_level = state["backoff_level"]
                        state["backoff_level"] = old_level + 1
                        backoff_minutes = min(
                            MAX_BACKOFF_MINUTES, BASE_BACKOFF_MINUTES * (2 ** state["backoff_level"])
                        )
                        state["skip_until"] = now_epoch + backoff_minutes * 60
                        if old_level == 0:
                            notify(
                                "Atleta monitor: backoff geactiveerd",
                                f"HTTP {status} ontvangen (browser-modus). Poll-interval tijdelijk naar {backoff_minutes} min.",
                                4,
                            )
                    else:
                        print(f"Unexpected status {status}, leaving state unchanged.")
                else:
                    print("No response captured after click (timeout).")

            today = time.strftime("%Y-%m-%d", time.gmtime())
            if state["last_heartbeat_date"] != today:
                notify(
                    "Atleta monitor: heartbeat",
                    f"De poller (browser-modus) draait nog. Laatste status: available={state['available']}.",
                    1,
                )
                state["last_heartbeat_date"] = today

            save_state(state)
            commit_state_if_changed()

            time.sleep(CHECK_INTERVAL_SECONDS)

        browser.close()


if __name__ == "__main__":
    main()
