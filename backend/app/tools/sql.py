"""run_sql: free-form SELECT queries written by the LLM, for questions no stats tool covers.

Defense in depth — each layer alone should be enough:
  1. The pundit_ro role can only SELECT from the public tables (db/readonly_role.sql).
  2. Every transaction is read-only and has a statement timeout (set by the role and again here).
  3. Only a single SELECT/WITH statement is accepted; parameters force Postgres' extended
     protocol, which rejects multi-statement strings.
  4. Results are capped in rows and characters, so a huge result can't flood the context.
"""

import re

import psycopg
from psycopg.rows import dict_row

from app.config import settings
from app.tools.stats import clean

MAX_ROWS = 100
MAX_CHARS = 20_000
TIMEOUT_MS = 3000

ALLOWED_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)

SCHEMA_DOC = """\
Tables (PostgreSQL). Seasons are text like '2026/2027'.
teams(id, name, badge_url)
players(key, name, display_name, position)  -- position: Goalkeepers/Defenders/Midfielders/Forwards
fixtures(id, season, round, stage, kickoff_utc, status, home_team_id, away_team_id, home_score, away_score,
         home_ht_score, away_ht_score, home_formation, away_formation, stadium, referee, details_fetched,
         goals_complete)  -- goals_complete=false: provider's goal events don't add up to the score
         -- played matches: status IN ('FINISHED','AWARDED') AND home_score IS NOT NULL
lineups(fixture_id, team_id, player_key, role, shirt_number)  -- role: starter/substitute/coach
goals(id, fixture_id, team_id, minute, minute_text, scorer_key, scorer_name, assist_key, assist_name, info)
         -- team_id = team credited with the goal; info = 'Penalty' for penalties
match_stats(fixture_id, team_id, stat, value)  -- one row per stat per team, e.g. stat='Shots Total'
         -- stats: Attacks, Ball Possession, Corners, Dangerous Attacks, Fouls, Offsides, On Target,
         --        Passes Accurate, Passes Total, Red Cards, Saves, Shots Blocked, Shots Inside Box,
         --        Shots Off Goal, Shots On Goal, Shots Outside Box, Shots Total, Yellow Cards
Group and label players by joining players ON key = scorer_key / assist_key / player_key and using
players.display_name: scorer_name/assist_name are raw provider spellings and split one player into several.
Use unaccent(lower(name)) for name matching."""


def run_sql(query: str) -> dict:
    """Tool: run one LLM-written SELECT through the read-only role. Errors are returned, not raised,
    so the model can read the message and fix its query.
    """
    query = query.strip().rstrip(";").strip()
    if not ALLOWED_START.match(query):
        return {"error": "Only a single SELECT (or WITH ... SELECT) query is allowed."}
    if ";" in query:
        return {"error": "Only one statement is allowed; remove the ';'."}

    try:
        with psycopg.connect(
            settings.database_url_readonly,
            row_factory=dict_row,
            options=f"-c statement_timeout={TIMEOUT_MS} -c default_transaction_read_only=on",
        ) as conn:
            with conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                # Empty params -> extended protocol (one statement only); '%' must then be escaped
                # so LIKE '%x%' isn't read as a placeholder.
                cur = conn.execute(query.replace("%", "%%"), ())
                rows = cur.fetchmany(MAX_ROWS + 1)
    except psycopg.Error as e:
        # The message goes back to the model so it can fix its query.
        return {"error": f"{type(e).__name__}: {str(e).strip().splitlines()[0]}"}

    truncated = len(rows) > MAX_ROWS
    rows = clean(rows[:MAX_ROWS])
    result = {"row_count": len(rows), "truncated": truncated, "rows": rows}
    text = str(result)
    if len(text) > MAX_CHARS:
        keep = max(1, int(len(rows) * MAX_CHARS / len(text)))
        result = {"row_count": keep, "truncated": True, "rows": rows[:keep]}
    return result
