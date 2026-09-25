"""Integration tests against the local football DB.

They assert invariants that hold for any data (totals add up, security boundaries hold),
so they don't break when a new round is ingested. Skipped if the DB is unreachable.
"""

import sys
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import connect  # noqa: E402
from app.ingest.players import names_compatible  # noqa: E402
from app.tools import stats  # noqa: E402
from app.tools.lookup import find_player, find_team  # noqa: E402
from app.tools.registry import TOOLS, call_tool  # noqa: E402
from app.tools.sql import run_sql  # noqa: E402


@pytest.fixture(scope="module")
def conn():
    try:
        c = connect()
        c.autocommit = True  # one failing query must not abort the shared connection for other tests
    except psycopg.OperationalError:
        pytest.skip("local Postgres not available")
    yield c
    c.close()


# ------------------------------------------------------------------ name resolution

@pytest.mark.parametrize("query, expected", [
    ("Maccabi Haifa", "Maccabi Haifa"),
    ("מכבי חיפה", "Maccabi Haifa"),
    ('הפועל פ"ת', "Hapoel Petah Tikva"),   # ASCII quote instead of gershayim
    ("ביתר", "Beitar Jerusalem"),
    ("Beer Sheva", "Hapoel Be'er Sheva"),
    ("macabi tel aviv", "Maccabi Tel Aviv"),  # typo
])
def test_find_team(conn, query, expected):
    assert find_team(conn, query).match["name"] == expected


def test_find_player_accent_insensitive(conn):
    assert find_player(conn, "Matheus Davo").match["name"] == "Matheus Davó"


def test_ambiguous_surname_returns_candidates(conn):
    result = find_player(conn, "Cohen")
    assert result.match is None and len(result.candidates) > 1


def test_names_compatible():
    assert names_compatible("D. Peretz", "Dor Peretz")
    assert names_compatible("dor peretz", "Dor Peretz")
    assert not names_compatible("N. Cohen", "Y. Cohen")
    assert not names_compatible("Dor Peretz", "Omer Peretz")


# ------------------------------------------------------------------ stats invariants

def test_league_table_is_consistent(conn):
    table = stats.league_table(conn)["table"]
    assert sum(r["goals_for"] for r in table) == sum(r["goals_against"] for r in table)
    assert sum(r["won"] for r in table) == sum(r["lost"] for r in table)
    for r in table:
        assert r["played"] == r["won"] + r["drawn"] + r["lost"]
        assert r["points"] == 3 * r["won"] + r["drawn"]
    points = [r["points"] for r in table]
    assert points == sorted(points, reverse=True)


def test_home_plus_away_equals_total(conn):
    total = {r["team"]: r["points"] for r in stats.league_table(conn)["table"]}
    home = {r["team"]: r["points"] for r in stats.league_table(conn, venue="home")["table"]}
    away = {r["team"]: r["points"] for r in stats.league_table(conn, venue="away")["table"]}
    for team, pts in total.items():
        assert home.get(team, 0) + away.get(team, 0) == pts


def test_every_raw_goal_event_became_a_row(conn):
    """Our normalization must not drop goals (provider gaps are a separate, known issue)."""
    mismatches = conn.execute(
        """
        SELECT count(*) AS n FROM fixtures f
        JOIN raw.api_responses r ON r.endpoint = '/fixtures/' || f.id || '/events'
        WHERE f.details_fetched
          AND (SELECT count(*) FROM jsonb_array_elements(r.payload -> 'data') e WHERE e ->> 'type' = 'GOAL')
              <> (SELECT count(*) FROM goals g WHERE g.fixture_id = f.id)
        """
    ).fetchone()["n"]
    assert mismatches == 0


def test_goals_complete_flag_matches_scores(conn):
    wrong = conn.execute(
        """
        SELECT count(*) AS n FROM fixtures f
        WHERE f.details_fetched AND f.goals_complete IS DISTINCT FROM
              ((SELECT count(*) FROM goals g WHERE g.fixture_id = f.id) = f.home_score + f.away_score)
        """
    ).fetchone()["n"]
    assert wrong == 0


def test_top_scorer_goals_match_player_stats(conn):
    top = stats.top_scorers(conn, limit=1)["players"][0]
    player = stats.player_stats(conn, top["player"], team=top["team"])
    season_row = next(s for s in player["seasons"] if s["season"] == stats.current_season(conn))
    assert season_row["goals"] == top["goals"]


def test_unknown_team_is_an_error_not_a_guess(conn):
    assert "error" in stats.team_form(conn, "Real Madrid")


# ------------------------------------------------------------------ run_sql security

@pytest.mark.parametrize("query", [
    "DELETE FROM goals",
    "SELECT 1; DELETE FROM goals",
    "WITH x AS (DELETE FROM goals RETURNING *) SELECT * FROM x",
    "UPDATE players SET name = 'x'",
    "SELECT * FROM raw.api_responses",
    "SELECT pg_sleep(10)",
    "SET statement_timeout = 0",
])
def test_run_sql_blocks_dangerous_queries(conn, query):
    before = conn.execute("SELECT count(*) AS n FROM goals").fetchone()["n"]
    assert "error" in run_sql(query)
    assert conn.execute("SELECT count(*) AS n FROM goals").fetchone()["n"] == before


def test_run_sql_allows_like_with_percent(conn):
    result = run_sql("SELECT name FROM players WHERE name LIKE '%Peretz%'")
    assert "error" not in result and result["row_count"] > 0


def test_run_sql_caps_rows(conn):
    result = run_sql("SELECT * FROM lineups")
    assert result["truncated"] and result["row_count"] <= 100


# ------------------------------------------------------------------ registry

def test_every_tool_is_callable():
    minimal_args = {"player_stats": {"player": "Dor Peretz"}, "team_form": {"team": "Maccabi Haifa"},
                    "head_to_head": {"team_a": "Maccabi Haifa", "team_b": "Maccabi Tel Aviv"},
                    "team_match_stats": {"team": "Maccabi Haifa"}, "match_report": {"team_a": "Maccabi Haifa"},
                    "run_sql": {"query": "SELECT 1 AS one"}}
    for tool in TOOLS:
        result = call_tool(tool["name"], minimal_args.get(tool["name"], {}))
        assert "error" not in result, (tool["name"], result)


def test_bad_arguments_return_error():
    assert "error" in call_tool("player_stats", {"playr": "x"})
    assert "error" in call_tool("no_such_tool", {})
