"""Probe Goal API (goal-api.com) coverage for the Israeli Premier League.

Usage (from backend/):
    python scripts/check_goal_api.py

Prints raw, truncated responses — the goal is to see what the free plan really returns.
"""

import json
import os
import sys

import httpx
from dotenv import load_dotenv

BASE_URL = "https://api.goal-api.com/v1"


def show(client: httpx.Client, path: str, **params) -> object:
    resp = client.get(path, params=params)
    limits = {k: v for k, v in resp.headers.items() if "limit" in k.lower() or "quota" in k.lower()}
    print(f"\n=== GET {path} {params or ''} -> {resp.status_code} {limits or ''}")
    try:
        body = resp.json()
    except ValueError:
        print(resp.text[:500])
        return None
    print(json.dumps(body, ensure_ascii=False, indent=1)[:1500])
    return body


def items(body: object) -> list:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("data", "response", "results", "leagues", "items"):
            if isinstance(body.get(key), list):
                return body[key]
    return []


def main() -> None:
    load_dotenv()
    key = os.getenv("GOAL_API_KEY")
    if not key:
        sys.exit("GOAL_API_KEY missing in .env")

    headers = {"Authorization": f"Bearer {key}"}
    with httpx.Client(base_url=BASE_URL, headers=headers, timeout=20) as client:
        leagues = items(show(client, "/leagues"))
        israeli = [
            lg for lg in leagues
            if "israel" in json.dumps(lg, ensure_ascii=False).lower()
            or "ha'al" in json.dumps(lg, ensure_ascii=False).lower()
        ]
        print(f"\n{len(leagues)} leagues on first page, Israeli matches: {len(israeli)}")
        for lg in israeli:
            print("  ", json.dumps(lg, ensure_ascii=False)[:300])

        if not israeli:
            return
        league_id = israeli[0].get("id")
        show(client, f"/leagues/{league_id}")
        show(client, f"/leagues/{league_id}/standings")
        show(client, f"/leagues/{league_id}/top-scorers")
        fixtures = items(show(client, f"/leagues/{league_id}/fixtures"))
        if fixtures and fixtures[0].get("id"):
            fixture_id = fixtures[0]["id"]
            show(client, f"/fixtures/{fixture_id}/events")
            show(client, f"/fixtures/{fixture_id}/statistics")


if __name__ == "__main__":
    main()
