"""Normalize Goal API responses into the public tables.

sync_fixtures  — fixture list for the league (all seasons), plus teams.
sync_details   — lineups, goals and match stats for finished fixtures, newest first,
                 until the request budget or the daily quota runs out. Resumable.
"""

import logging
from datetime import datetime

from psycopg import Connection

from app.sources.goal_api import GoalApiClient, QuotaExhausted

log = logging.getLogger(__name__)

LINEUP_ROLES = {"startingLineups": "starter", "substitutes": "substitute", "coach": "coach"}


def to_int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def player_key(value) -> str | None:
    """The API uses '0' (and sometimes '') for players it could not identify."""
    value = str(value or "").strip()
    return value if value not in ("", "0") else None


def to_number(value) -> float | None:
    try:
        return float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None


def upsert_team(conn: Connection, team_id: str, name: str, badge_url: str | None) -> None:
    conn.execute(
        """
        INSERT INTO teams (id, name, badge_url) VALUES (%s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, badge_url = EXCLUDED.badge_url
        """,
        (team_id, name, badge_url),
    )


def sync_fixtures(conn: Connection, client: GoalApiClient, league_id: str, refresh: bool = True) -> int:
    fixtures = client.get_all_pages(f"/leagues/{league_id}/fixtures", refresh=refresh)
    for f in fixtures:
        upsert_team(conn, f["homeTeamId"], f["homeTeam"]["name"], f["homeTeam"].get("badge"))
        upsert_team(conn, f["awayTeamId"], f["awayTeam"]["name"], f["awayTeam"].get("badge"))
        conn.execute(
            """
            INSERT INTO fixtures (id, season, round, stage, kickoff_utc, status,
                                  home_team_id, away_team_id, home_score, away_score,
                                  home_ht_score, away_ht_score, home_formation, away_formation,
                                  stadium, referee)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                season = EXCLUDED.season, round = EXCLUDED.round, stage = EXCLUDED.stage,
                kickoff_utc = EXCLUDED.kickoff_utc, status = EXCLUDED.status,
                home_score = EXCLUDED.home_score, away_score = EXCLUDED.away_score,
                home_ht_score = EXCLUDED.home_ht_score, away_ht_score = EXCLUDED.away_ht_score,
                home_formation = EXCLUDED.home_formation, away_formation = EXCLUDED.away_formation,
                stadium = EXCLUDED.stadium, referee = EXCLUDED.referee,
                -- a fixture that just finished needs its details (re)loaded
                details_fetched = fixtures.details_fetched AND fixtures.status = EXCLUDED.status
            """,
            (
                f["id"], f["leagueYear"], to_int(f["matchRound"]), f["stageName"],
                datetime.fromisoformat(f["kickoffUtc"].replace("Z", "+00:00")), f["matchStatus"],
                f["homeTeamId"], f["awayTeamId"], to_int(f["homeTeamScore"]), to_int(f["awayTeamScore"]),
                to_int(f["homeTeamHalftimeScore"]), to_int(f["awayTeamHalftimeScore"]),
                f["homeTeamSystem"], f["awayTeamSystem"], f["matchStadium"], f["matchReferee"],
            ),
        )
    conn.commit()
    return len(fixtures)


def load_fixture_details(conn: Connection, client: GoalApiClient, fixture: dict) -> None:
    fid = fixture["id"]
    team_by_side = {"home": fixture["home_team_id"], "away": fixture["away_team_id"]}

    lineups = client.get(f"/fixtures/{fid}/lineups")["data"]
    goals = client.get(f"/fixtures/{fid}/events")["data"]
    stats = client.get(f"/fixtures/{fid}/statistics")["data"]

    conn.execute("DELETE FROM lineups WHERE fixture_id = %s", (fid,))
    conn.execute("DELETE FROM goals WHERE fixture_id = %s", (fid,))
    conn.execute("DELETE FROM match_stats WHERE fixture_id = %s", (fid,))

    for side in ("home", "away"):
        for group, role in LINEUP_ROLES.items():
            for p in (lineups.get(side) or {}).get(group) or []:
                key = player_key(p.get("playerKey"))
                if not key:
                    continue
                conn.execute(
                    """
                    INSERT INTO players (key, name, position, image_url) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (key) DO UPDATE SET
                        -- never replace a full name with an abbreviated one
                        name      = CASE WHEN EXCLUDED.name ~ '^[A-Z]\\.' AND players.name !~ '^[A-Z]\\.'
                                         THEN players.name ELSE EXCLUDED.name END,
                        position  = COALESCE(EXCLUDED.position, players.position),
                        image_url = COALESCE(EXCLUDED.image_url, players.image_url)
                    """,
                    (key, p["lineupPlayer"], p.get("playerPosition"), p.get("playerImage")),
                )
                conn.execute(
                    """
                    INSERT INTO lineups (fixture_id, team_id, player_key, role, shirt_number)
                    VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
                    """,
                    (fid, team_by_side[side], key, role, to_int(p.get("lineupNumber"))),
                )

    for g in goals:
        if g["type"] != "GOAL":
            continue
        side = "home" if g.get("homeScorer") or player_key(g.get("homeScorerId")) else "away"
        scorer_key, assist_key = player_key(g.get(f"{side}ScorerId")), player_key(g.get(f"{side}AssistId"))
        # Scorers missing from the lineup (rare) still get a player row, with the short name.
        for key, name in ((scorer_key, g.get(f"{side}Scorer")), (assist_key, g.get(f"{side}Assist"))):
            if key:
                conn.execute(
                    "INSERT INTO players (key, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (key, name or key),
                )
        conn.execute(
            """
            INSERT INTO goals (id, fixture_id, team_id, minute, minute_text,
                               scorer_key, scorer_name, assist_key, assist_name, info)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                g["id"], fid, team_by_side[side], g.get("timeNum"), g.get("time"),
                scorer_key, g.get(f"{side}Scorer"), assist_key, g.get(f"{side}Assist"), g.get("info"),
            ),
        )

    for s in ((stats or {}).get("match") or {}).get("fullTime") or []:
        for side in ("home", "away"):
            # The API sometimes repeats a stat type; the first occurrence wins.
            conn.execute(
                """
                INSERT INTO match_stats (fixture_id, team_id, stat, value)
                VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING
                """,
                (fid, team_by_side[side], s["type"], to_number(s.get(side))),
            )

    conn.execute("UPDATE fixtures SET details_fetched = true WHERE id = %s", (fid,))


def sync_details(conn: Connection, client: GoalApiClient, max_fixtures: int | None = None) -> int:
    pending = conn.execute(
        """
        SELECT id, home_team_id, away_team_id FROM fixtures
        WHERE status = 'FINISHED' AND NOT details_fetched
        ORDER BY kickoff_utc DESC
        """
    ).fetchall()
    if max_fixtures is not None:
        pending = pending[:max_fixtures]

    done = 0
    for fixture in pending:
        try:
            load_fixture_details(conn, client, fixture)
        except QuotaExhausted as e:
            conn.rollback()
            log.warning("Stopping: %s", e)
            break
        conn.commit()
        done += 1
        if done % 25 == 0:
            log.info("%d/%d fixtures loaded (quota left: %s)", done, len(pending), client.remaining)
    return done
