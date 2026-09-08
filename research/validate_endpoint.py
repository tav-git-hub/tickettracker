#!/usr/bin/env python3
"""
Step 2 (research): validate that a captured availability call is
reproducible WITHOUT a session cookie, and check for rate limiting.

Run this LOCALLY (on your laptop), not in a sandboxed/cloud environment.

Usage:
    python3 validate_endpoint.py capture.json
    python3 validate_endpoint.py capture.json --index 0

By default it inspects capture.json (produced by capture_xhr.py) and lets
you pick which captured call to validate if there's more than one
candidate. It then:

  1. Replays the call with `requests`, stripping Cookie/Authorization/
     session-ish headers, and reports whether the response still looks
     like a valid availability response.
  2. Fires the same call 5x back-to-back and reports status codes,
     timing, and any Retry-After / rate-limit headers.

It prints a human-readable report and writes validation_report.json.
"""
import argparse
import json
import sys
import time

try:
    import requests
except ImportError:
    print("Missing dependency. Run: pip install requests")
    sys.exit(1)

STRIP_HEADER_PREFIXES = ("cookie", "authorization", "x-csrf", "x-xsrf")
# Headers that are connection/browser-internal and shouldn't be replayed as-is
DROP_HEADERS = {
    "cookie",
    "authorization",
    "content-length",
    "host",
    ":authority",
    ":method",
    ":path",
    ":scheme",
}


def load_candidates(path):
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = [data]
    return data


def pick_candidate(entries, index):
    if index is not None:
        return entries[index]
    if len(entries) == 1:
        return entries[0]
    print(f"Found {len(entries)} captured XHR/fetch calls:")
    for i, e in enumerate(entries):
        print(f"  [{i}] {e.get('method')} {e.get('url')} -> {e.get('status')}")
    choice = input("Which index looks like the availability call? ")
    return entries[int(choice.strip())]


def clean_headers(headers):
    cleaned = {}
    for k, v in (headers or {}).items():
        if k.lower() in DROP_HEADERS:
            continue
        if any(k.lower().startswith(p) for p in STRIP_HEADER_PREFIXES):
            continue
        cleaned[k] = v
    cleaned["User-Agent"] = "AtletaResaleMonitor-Research/1.0 (personal, non-automated check)"
    return cleaned


def do_request(url, method, headers, body):
    kwargs = {"headers": headers, "timeout": 15}
    if body:
        kwargs["data"] = body
    t0 = time.monotonic()
    resp = requests.request(method, url, **kwargs)
    elapsed = time.monotonic() - t0
    return resp, elapsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_file", help="JSON file from capture_xhr.py")
    parser.add_argument("--index", type=int, default=None, help="Which captured entry to use")
    parser.add_argument("--bursts", type=int, default=5, help="Number of rapid-fire requests")
    parser.add_argument("--output", default="validation_report.json")
    args = parser.parse_args()

    entries = load_candidates(args.capture_file)
    if not entries:
        print("No entries in capture file.")
        sys.exit(1)

    candidate = pick_candidate(entries, args.index)
    url = candidate["url"]
    method = candidate.get("method", "GET")
    body = candidate.get("post_data")
    headers = clean_headers(candidate.get("request_headers"))

    report = {"url": url, "method": method, "headers_sent": headers}

    print()
    print(f"=== Reproducibility check (no cookie) ===")
    print(f"{method} {url}")
    try:
        resp, elapsed = do_request(url, method, headers, body)
        print(f"Status: {resp.status_code}  ({elapsed:.2f}s)")
        snippet = resp.text[:1000]
        print(f"Body (first 1000 chars):\n{snippet}")
        report["single_request"] = {
            "status": resp.status_code,
            "elapsed_s": elapsed,
            "response_headers": dict(resp.headers),
            "body_snippet": snippet,
        }
        if resp.status_code >= 400:
            print()
            print("WARNING: non-2xx status without cookie. The endpoint may")
            print("require an authenticated/browser session after all.")
    except Exception as e:
        print(f"Request failed: {e}")
        report["single_request"] = {"error": str(e)}

    print()
    print(f"=== Rate-limit check ({args.bursts}x back-to-back) ===")
    burst_results = []
    for i in range(args.bursts):
        try:
            resp, elapsed = do_request(url, method, headers, body)
            retry_after = resp.headers.get("Retry-After")
            print(
                f"  request {i + 1}: status={resp.status_code} "
                f"time={elapsed:.2f}s"
                + (f" Retry-After={retry_after}" if retry_after else "")
            )
            burst_results.append(
                {
                    "status": resp.status_code,
                    "elapsed_s": elapsed,
                    "retry_after": retry_after,
                }
            )
        except Exception as e:
            print(f"  request {i + 1}: FAILED ({e})")
            burst_results.append({"error": str(e)})
    report["burst_requests"] = burst_results

    rate_limited = any(
        r.get("status") in (429, 403) for r in burst_results if "status" in r
    )
    print()
    if rate_limited:
        print("=> Rate limiting / blocking observed during burst. Build in")
        print("   backoff and don't poll faster than necessary.")
    else:
        print("=> No 429/403 observed during burst (small sample; stay conservative anyway).")

    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nFull report written to {args.output}")


if __name__ == "__main__":
    main()
