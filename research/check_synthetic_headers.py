#!/usr/bin/env python3
"""
Check whether the GetRegistrationsForSale call works with fully
fabricated (non-browser-derived) atleta-session-id / x-xsrf-token
values, and whether it works with those headers omitted entirely.
Pure `requests`, no Playwright. Prints JSON results to stdout.
"""
import json
import random
import string
import sys

import requests

URL = "https://atleta.cc/api/graphql"
QUERY = {
    "operationName": "GetRegistrationsForSale",
    "variables": {"id": "qPULqpd5Gtfm", "tickets": None, "limit": 10},
    "query": (
        "query GetRegistrationsForSale($id: ID!, $tickets: [String!], $limit: Int!, "
        "$invitation_code: String) {\n  event(id: $id) {\n    id\n    "
        "registrations_for_sale_count\n    sold_registrations_count\n    __typename\n  }\n}"
    ),
}


def random_session_id():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=20))


def try_request(label, headers):
    try:
        resp = requests.post(URL, headers=headers, data=json.dumps(QUERY), timeout=15)
        return {
            "label": label,
            "status": resp.status_code,
            "body": resp.text[:800],
        }
    except Exception as e:
        return {"label": label, "error": str(e)}


def main():
    base_headers = {
        "content-type": "application/json",
        "accept": "*/*",
        "referer": "https://atleta.cc/e/qPULqpd5Gtfm/resale",
        "User-Agent": "AtletaResaleMonitor-Validation/1.0 (synthetic header check)",
    }

    results = []

    # 1. No session/xsrf headers at all
    results.append(try_request("no_session_headers", dict(base_headers)))

    # 2. Fully fabricated atleta-session-id, no xsrf token
    h2 = dict(base_headers)
    h2["atleta-session-id"] = random_session_id()
    results.append(try_request("fabricated_session_id_only", h2))

    # 3. Fabricated atleta-session-id + garbage xsrf token
    h3 = dict(base_headers)
    h3["atleta-session-id"] = random_session_id()
    h3["x-xsrf-token"] = "not-a-real-token"
    results.append(try_request("fabricated_session_id_and_garbage_xsrf", h3))

    print(json.dumps(results))


if __name__ == "__main__":
    main()
