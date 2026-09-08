#!/usr/bin/env python3
"""
Step 1 (research): capture the XHR/fetch call fired by the Atleta resale
refresh button.

Run this LOCALLY (on your laptop), not in a sandboxed/cloud environment --
some sandboxes block outbound access to atleta.cc at the network-policy
level.

Usage:
    pip install playwright
    playwright install chromium
    python3 capture_xhr.py
    python3 capture_xhr.py --url https://atleta.cc/e/qPULqpd5Gtfm/resale
    python3 capture_xhr.py --auto-click "text=Refresh" --clicks 2

A Chromium window opens on the resale page. By default the script just
records every XHR/fetch call while you manually click the refresh button
in that window (click it once or a few times), then press Enter in this
terminal when done. If you already know the button's selector, pass
--auto-click to have Playwright click it for you instead.

Output: capture.json in the current directory, containing for every
XHR/fetch request: full URL, method, request headers, request body,
response status, response headers, and response body.
"""
import argparse
import json
import sys
import time

DEFAULT_URL = "https://atleta.cc/e/qPULqpd5Gtfm/resale"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="Page to load")
    parser.add_argument(
        "--auto-click",
        default=None,
        help="Playwright selector for the refresh button (skips manual click)",
    )
    parser.add_argument(
        "--clicks", type=int, default=1, help="Number of times to auto-click"
    )
    parser.add_argument(
        "--click-delay", type=float, default=2.0, help="Seconds between auto-clicks"
    )
    parser.add_argument("--output", default="capture.json", help="Output JSON file")
    parser.add_argument(
        "--headless", action="store_true", help="Run headless (only useful with --auto-click)"
    )
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    captured = []

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
        print(f"[captured #{len(captured)}] {request.method} {request.url} -> {entry.get('status')}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context()
        page = context.new_page()
        page.on("requestfinished", on_request_finished)

        print(f"Loading {args.url} ...")
        page.goto(args.url, wait_until="networkidle")

        if args.auto_click:
            for i in range(args.clicks):
                print(f"Auto-clicking '{args.auto_click}' ({i + 1}/{args.clicks}) ...")
                page.click(args.auto_click)
                time.sleep(args.click_delay)
        else:
            print()
            print("A browser window is open on the resale page.")
            print("Manually click the refresh/availability-check button now")
            print("(click it a couple of times if you like, to see if the")
            print("call is identical each time).")
            input("Press Enter here when you're done clicking... ")

        browser.close()

    with open(args.output, "w") as f:
        json.dump(captured, f, indent=2)

    print()
    print(f"Captured {len(captured)} XHR/fetch call(s) -> {args.output}")
    if not captured:
        print("No XHR/fetch calls captured. Either the button didn't trigger")
        print("a network call (e.g. it just re-reads already-loaded data),")
        print("or it uses a request type this script doesn't watch for.")
        print("Open DevTools > Network manually to double-check.")


if __name__ == "__main__":
    main()
