#!/usr/bin/env python3
"""One-off diagnostic: figure out why the resale panel (refresh button,
ticket counts) isn't showing up in a fresh Playwright session."""
import re
import sys

from playwright.sync_api import sync_playwright

URL = "https://atleta.cc/e/qPULqpd5Gtfm/resale"

captured = []


def on_request_finished(request):
    if request.resource_type not in ("xhr", "fetch"):
        return
    if "GetRegistrationsForSale" not in (request.post_data or ""):
        return
    try:
        resp = request.response()
        captured.append({"status": resp.status if resp else None})
    except Exception as e:
        captured.append({"error": str(e)})


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.on("requestfinished", on_request_finished)
    page.goto(URL, wait_until="networkidle", timeout=30000)

    for text in ("Accept", "Reject", "Accepteren", "Weigeren"):
        try:
            page.locator(f"text={text}").first.click(timeout=2000)
            print(f"[diag] dismissed cookie banner via {text!r}", file=sys.stderr)
            break
        except Exception:
            continue

    print(f"[diag] URL after load: {page.url}", file=sys.stderr)

    # Give the SPA extra time beyond networkidle to lazy-render the panel.
    page.wait_for_timeout(5000)

    print(f"[diag] URL after wait: {page.url}", file=sys.stderr)
    print(f"[diag] GetRegistrationsForSale calls captured so far: {captured}", file=sys.stderr)

    html = page.content()
    print(f"=== content length: {len(html)} ===")
    for kw in ("vernieuw", "ticketdoorverkoop", "beschikbaar", "verkocht", "registrations_for_sale", "resale"):
        n = len(re.findall(kw, html, re.IGNORECASE))
        print(f"keyword {kw!r}: {n} occurrences")

    print("=== all visible text nodes (body innerText, first 3000 chars) ===")
    try:
        body_text = page.locator("body").inner_text(timeout=3000)
    except Exception as e:
        body_text = f"<error: {e}>"
    print(body_text[:3000])

    print("=== final captured GetRegistrationsForSale calls ===")
    print(captured)

    browser.close()
