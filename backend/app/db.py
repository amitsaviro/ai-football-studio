"""Postgres connection helpers.

Rows come back as dicts (dict_row) so tools can return them as JSON without extra mapping.
"""

from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from app.config import settings

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def connect() -> psycopg.Connection:
    """Open a connection with the admin role (used by ingestion and the stats tools)."""
    return psycopg.connect(settings.database_url, row_factory=dict_row)


def init_schema(conn: psycopg.Connection) -> None:
    """Create schemas/tables/extensions if missing. Safe to run on every start (idempotent)."""
    conn.execute(SCHEMA_PATH.read_text())
    conn.commit()
