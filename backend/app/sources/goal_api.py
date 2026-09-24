"""Goal API client with a raw-response cache in Postgres.

Every successful response is stored in raw.api_responses. Cached endpoints are served
from the DB, so re-running ingestion (or re-normalizing after a schema change) costs no quota.
"""

import logging
from urllib.parse import urlencode

import httpx
from psycopg import Connection
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)

BASE_URL = "https://api.goal-api.com/v1"
SOURCE = "goal_api"


class QuotaExhausted(Exception):
    """Raised to stop a run cleanly: daily quota nearly used up, or a cache miss in offline mode."""


class GoalApiClient:
    """HTTP client for Goal API that checks the raw cache before spending a request."""
    def __init__(self, conn: Connection, api_key: str, quota_reserve: int = 20, offline: bool = False):
        if not api_key and not offline:
            raise ValueError("GOAL_API_KEY is not set")
        self.conn = conn
        self.offline = offline  # serve from cache only; a cache miss stops the run
        self.quota_reserve = quota_reserve  # stop before hitting zero; leave room for manual checks
        self.remaining: int | None = None
        self.requests_made = 0
        self.http = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
            transport=httpx.HTTPTransport(retries=3),
        )

    def get(self, path: str, refresh: bool = False, **params) -> dict:
        """GET one endpoint. Returns the cached payload unless refresh=True; otherwise calls the API,
        updates the remaining-quota counter from the response headers and stores the payload in raw.api_responses.
        """
        endpoint = f"{path}?{urlencode(sorted(params.items()))}" if params else path
        if not refresh:
            row = self.conn.execute(
                "SELECT payload FROM raw.api_responses WHERE source = %s AND endpoint = %s",
                (SOURCE, endpoint),
            ).fetchone()
            if row:
                return row["payload"]

        if self.offline:
            raise QuotaExhausted(f"offline mode and {endpoint} is not cached")
        if self.remaining is not None and self.remaining <= self.quota_reserve:
            raise QuotaExhausted(f"{self.remaining} requests left today")

        resp = self.http.get(path, params=params)
        self.requests_made += 1
        if "x-ratelimit-remaining" in resp.headers:
            self.remaining = int(resp.headers["x-ratelimit-remaining"])
        if resp.status_code == 429:
            raise QuotaExhausted("HTTP 429 from Goal API")
        resp.raise_for_status()

        body = resp.json()
        self.conn.execute(
            """
            INSERT INTO raw.api_responses (source, endpoint, status_code, payload)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (source, endpoint)
            DO UPDATE SET status_code = EXCLUDED.status_code,
                          payload     = EXCLUDED.payload,
                          fetched_at  = now()
            """,
            (SOURCE, endpoint, resp.status_code, Jsonb(body)),
        )
        return body

    def get_all_pages(self, path: str, refresh: bool = False, page_size: int = 100) -> list[dict]:
        """Follow offset/limit pagination until the API says hasMore=false; returns all `data` items."""
        items, offset = [], 0
        while True:
            body = self.get(path, refresh=refresh, limit=page_size, offset=offset)
            items.extend(body["data"])
            if not body.get("pagination", {}).get("hasMore"):
                return items
            offset += page_size
