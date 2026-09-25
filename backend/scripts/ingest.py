"""Sync Ligat Ha'al data from Goal API into Postgres.

Usage (from backend/):
    python scripts/ingest.py                  # fixtures + as many match details as the quota allows
    python scripts/ingest.py --max-fixtures 10
    python scripts/ingest.py --rebuild        # drop normalized tables, rebuild from raw cache (no quota)
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.db import connect, init_schema  # noqa: E402
from app.ingest.goal_api import sync_details, sync_fixtures  # noqa: E402
from app.ingest.players import resolve_players  # noqa: E402
from app.sources.goal_api import GoalApiClient, QuotaExhausted  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-fixtures", type=int, help="limit match-detail loads this run")
    parser.add_argument("--rebuild", action="store_true", help="rebuild normalized tables from raw cache")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    log = logging.getLogger("ingest")

    with connect() as conn:
        # Two runs at once would fetch the same fixtures twice and waste quota. A session-level
        # advisory lock lets only one run proceed; Postgres releases it when this connection closes.
        got_lock = conn.execute("SELECT pg_try_advisory_lock(hashtext('ingest')) AS ok").fetchone()["ok"]
        conn.commit()
        if not got_lock:
            log.error("Another ingestion run is already in progress; exiting.")
            sys.exit(1)

        if args.rebuild:
            conn.execute(
                "DROP TABLE IF EXISTS match_stats, goals, lineups, player_aliases, players, fixtures, teams"
            )
        init_schema(conn)
        client = GoalApiClient(settings.goal_api_key, offline=args.rebuild)

        try:
            n = sync_fixtures(conn, client, settings.goal_league_id, refresh=not args.rebuild)
        except QuotaExhausted as e:
            log.error("Could not refresh the fixture list (%s). Try again after the daily quota resets.", e)
            sys.exit(1)
        log.info("Fixtures synced: %d", n)

        done = sync_details(conn, client, args.max_fixtures)
        resolve_players(conn)
        pending = conn.execute(
            "SELECT count(*) AS n FROM fixtures WHERE status = 'FINISHED' AND NOT details_fetched"
        ).fetchone()["n"]
        log.info(
            "Details loaded: %d | still pending: %d | API requests this run: %d | quota left: %s",
            done, pending, client.requests_made, client.remaining,
        )


if __name__ == "__main__":
    main()
