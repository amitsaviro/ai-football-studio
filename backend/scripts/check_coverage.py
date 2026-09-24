"""Check what API-Football offers for Israeli leagues on the current plan.

Usage (from backend/):
    python scripts/check_coverage.py [season]   # season defaults to the latest one

Costs ~4 requests of the daily quota.
"""

import os
import sys

import httpx
from dotenv import load_dotenv

BASE_URL = "https://v3.football.api-sports.io"
LIGAT_HAAL_ID = 383


def get(client: httpx.Client, path: str, **params) -> dict:
    resp = client.get(path, params=params)
    resp.raise_for_status()
    body = resp.json()
    if body.get("errors"):
        print(f"  ! {path} {params}: {body['errors']}")
    return body


def main() -> None:
    load_dotenv()
    key = os.getenv("API_FOOTBALL_KEY")
    if not key:
        sys.exit("API_FOOTBALL_KEY missing — copy .env.example to .env and fill it in.")

    with httpx.Client(base_url=BASE_URL, headers={"x-apisports-key": key}, timeout=20) as client:
        status = get(client, "/status")["response"]
        if status:
            sub, req = status["subscription"], status["requests"]
            print(f"Plan: {sub['plan']} | requests today: {req['current']}/{req['limit_day']}\n")

        leagues = get(client, "/leagues", country="Israel")["response"]
        top_league = None
        for item in leagues:
            league = item["league"]
            print(f"[{league['id']}] {league['name']} ({league['type']})")
            if league["id"] == LIGAT_HAAL_ID:
                top_league = item
            for season in item["seasons"][-4:]:
                cov = season["coverage"]
                fx = cov["fixtures"]
                print(
                    f"   {season['year']}: events={fx['events']} lineups={fx['lineups']} "
                    f"fixture_stats={fx['statistics_fixtures']} player_stats={fx['statistics_players']} "
                    f"players={cov['players']} standings={cov['standings']}"
                )

        if top_league is None:
            sys.exit("\nNo Israeli league found.")

        # Coverage flags say what exists; a real call shows what the plan lets us read.
        season = int(sys.argv[1]) if len(sys.argv) > 1 else top_league["seasons"][-1]["year"]
        print(f"\nPlan access test — {top_league['league']['name']}, season {season}:")
        standings = get(client, "/standings", league=LIGAT_HAAL_ID, season=season)["response"]
        print(f"  standings: {'OK' if standings else 'empty / blocked'}")
        players = get(client, "/players", league=LIGAT_HAAL_ID, season=season, page=1)
        print(
            f"  players:   {len(players['response'])} on page 1 "
            f"(total pages: {players.get('paging', {}).get('total')})"
        )


if __name__ == "__main__":
    main()
