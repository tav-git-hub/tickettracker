#!/usr/bin/env python3
"""
Headless, non-interactive discovery script for GitHub Actions.

Loads the Atleta resale page, tries to find and click a refresh/check-
availability style button using text heuristics, and records every
XHR/fetch request+response seen from page load through a few seconds
after the click. Prints the result as JSON to stdout (picked up from the
job log) instead of writing a file, since this step is not interactive.
"""
import json
import re
import sys
import time

DEFAULT_URL = "https://atleta.cc/e/qPULqpd5Gtfm/resale"
BUTTON_TEXT_RE = re.compile(
    r"ververs|vernieuw|refresh|herlaad|reload|controleer|check|update|beschikbaar|availab",
    re.IGNORECASE,
)


def main():
    from playwright.sync_api import sync_playwright

    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    captured = []
    debug = {"buttons_seen": [], "click_attempted": False, "click_selector": None}

    def on_request_finished(request):
        if request.resource_type not in ("xhr", "fetch"):
            return
        entry = {
            "url": request.url,
            "method": request.method,
            "request_headers": request.headers,
            "post_data": request.post_data,
            "resource_type": request.resource_type,
        }
        try:
            response = request.response()
        except Exception as e:
            response = None
            entry["response_error"] = str(e)
        if response is not None:
            entry["status"] = response.status
            entry["response_headers"] = response.headers
            try:
                entry["response_body"] = response.text()
            except Exception as e:
                entry["response_body"] = f"<error reading body: {e}>"
        captured.append(entry)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        )
        page = context.new_page()
        page.on("requestfinished", on_request_finished)

        print(f"[discover] loading {url}", file=sys.stderr)
        page.goto(url, wait_until="networkidle", timeout=30000)
        time.sleep(2)

        # Log every clickable-looking element's text for debugging, and try
        # to find a refresh/check-availability button by text heuristic.
        candidates = page.locator("button, a[role=button], [role=button]")
        count = candidates.count()
        clicked = False
        for i in range(min(count, 50)):
            el = candidates.nth(i)
            try:
                text = (el.inner_text(timeout=1000) or "").strip()
            except Exception:
                text = ""
            if text:
                debug["buttons_seen"].append(text)
            if not clicked and text and BUTTON_TEXT_RE.search(text):
                try:
                    el.click(timeout=3000)
                    clicked = True
                    debug["click_attempted"] = True
                    debug["click_selector"] = f"button/[role=button] #{i} text={text!r}"
                    print(f"[discover] clicked candidate: {text!r}", file=sys.stderr)
                except Exception as e:
                    print(f"[discover] click failed on {text!r}: {e}", file=sys.stderr)

        if not clicked:
            print("[discover] no matching button found/clicked; only load-time XHR captured", file=sys.stderr)

        time.sleep(4)
        browser.close()

    print(json.dumps({"captured": captured, "debug": debug}))


if __name__ == "__main__":
    main()
