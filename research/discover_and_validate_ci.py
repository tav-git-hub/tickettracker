#!/usr/bin/env python3
"""
Fully automated, non-interactive discovery + validation for GitHub Actions.

1. Loads the Atleta resale page with Playwright and captures the
   GetRegistrationsForSale GraphQL call (the one carrying resale
   availability).
2. Immediately replays that exact call with a plain `requests` session
   (no cookies, no browser context) to check whether it's reproducible
   without a session cookie.
3. Fires it 5x back-to-back to check for rate limiting (429/403,
   Retry-After).

Prints one JSON object to stdout with the capture and both validation
results.
"""
import json
import re
import sys
import time

DEFAULT_URL = "https://atleta.cc/e/qPULqpd5Gtfm/resale"
GRAPHQL_URL = "https://atleta.cc/api/graphql"
TARGET_OPERATION = "GetRegistrationsForSale"

DROP_HEADERS = {
    "cookie",
    "authorization",
    "content-length",
    "host",
}


def capture(url):
    from playwright.sync_api import sync_playwright

    captured = []

    def on_request_finished(request):
        if request.resource_type not in ("xhr", "fetch"):
            return
        if TARGET_OPERATION not in (request.post_data or ""):
            return
        entry = {
            "url": request.url,
            "method": request.method,
            "request_headers": request.headers,
            "post_data": request.post_data,
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
        page.goto(url, wait_until="networkidle", timeout=30000)
        time.sleep(2)
        browser.close()

    return captured


def clean_headers(headers):
    cleaned = {k: v for k, v in (headers or {}).items() if k.lower() not in DROP_HEADERS}
    cleaned["User-Agent"] = "AtletaResaleMonitor-Validation/1.0 (automated reproducibility check)"
    return cleaned


def validate(entry, bursts=5):
    import requests

    url = entry["url"]
    method = entry.get("method", "POST")
    body = entry.get("post_data")
    headers = clean_headers(entry.get("request_headers"))
    had_cookie = "cookie" in {k.lower() for k in (entry.get("request_headers") or {})}

    result = {"had_cookie_in_original_request": had_cookie, "headers_sent": headers}

    try:
        t0 = time.monotonic()
        resp = requests.request(method, url, headers=headers, data=body, timeout=15)
        elapsed = time.monotonic() - t0
        result["single_request"] = {
            "status": resp.status_code,
            "elapsed_s": elapsed,
            "response_headers": dict(resp.headers),
            "body": resp.text[:3000],
        }
    except Exception as e:
        result["single_request"] = {"error": str(e)}

    burst_results = []
    for i in range(bursts):
        try:
            t0 = time.monotonic()
            resp = requests.request(method, url, headers=headers, data=body, timeout=15)
            elapsed = time.monotonic() - t0
            burst_results.append(
                {
                    "status": resp.status_code,
                    "elapsed_s": elapsed,
                    "retry_after": resp.headers.get("Retry-After"),
                    "x_ratelimit_remaining": resp.headers.get("X-RateLimit-Remaining")
                    or resp.headers.get("x-ratelimit-remaining"),
                }
            )
        except Exception as e:
            burst_results.append({"error": str(e)})
    result["burst_requests"] = burst_results

    return result


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    print(f"[ci] capturing from {url}", file=sys.stderr)
    captured = capture(url)
    print(f"[ci] captured {len(captured)} matching call(s)", file=sys.stderr)

    output = {"captured": captured, "validation": None}

    if captured:
        print("[ci] validating reproducibility + rate limiting", file=sys.stderr)
        output["validation"] = validate(captured[0])
    else:
        print("[ci] no GetRegistrationsForSale call captured; nothing to validate", file=sys.stderr)

    print(json.dumps(output))


if __name__ == "__main__":
    main()
