#!/usr/bin/env python3
"""One-off diagnostic: dump all clickable-element texts + raw HTML around
any occurrence of 'vernieuw' (case-insensitive) on the live resale page."""
import re
import sys

from playwright.sync_api import sync_playwright

URL = "https://atleta.cc/e/qPULqpd5Gtfm/resale"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(URL, wait_until="networkidle", timeout=30000)

    for text in ("Accept", "Reject", "Accepteren", "Weigeren"):
        try:
            page.locator(f"text={text}").first.click(timeout=2000)
            print(f"[diag] dismissed cookie banner via {text!r}", file=sys.stderr)
            break
        except Exception:
            continue

    page.wait_for_timeout(1500)

    for tab_text in ("Resale", "Doorverkoop"):
        try:
            page.locator(f"text={tab_text}").first.click(timeout=2000)
            print(f"[diag] clicked tab {tab_text!r}", file=sys.stderr)
            page.wait_for_timeout(2000)
            break
        except Exception as e:
            print(f"[diag] tab click {tab_text!r} failed: {e}", file=sys.stderr)

    print("=== clickable elements ===")
    candidates = page.locator("button, a, [role=button]")
    count = candidates.count()
    for i in range(min(count, 80)):
        el = candidates.nth(i)
        try:
            text = (el.inner_text(timeout=500) or "").strip()
        except Exception:
            text = "<err>"
        if text:
            print(f"[{i}] {text!r}")

    print("=== raw HTML around 'vernieuw' (case-insensitive) ===")
    html = page.content()
    for m in re.finditer(r"vernieuw", html, re.IGNORECASE):
        start = max(0, m.start() - 200)
        end = min(len(html), m.end() + 200)
        print(html[start:end])
        print("---")

    browser.close()
