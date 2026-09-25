"""Football stats tools. Every number the pundits say comes from one of these functions.

Each tool returns a JSON-serializable dict. Name resolution failures come back as
{"error": ..., "candidates": [...]} so the agent can ask which one was meant.
"""

from datetime import date, datetime
from decimal import Decimal

from psycopg import Connection

from app.tools.lookup import Lookup, find_player, find_team

PLAYED = "f.status IN ('FINISHED', 'AWARDED') AND f.home_score IS NOT NULL"


def clean(value):
    """Make DB values JSON-friendly."""
    if isinstance(value, Decimal):
        return float(round(value, 2))
    if isinstance(value, (datetime, date)):
        return value.isoformat()[:10]
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def current_season(conn: Connection) -> str:
    """Latest season that has at least one played match."""
    return conn.execute(f"SELECT max(season) AS s FROM fixtures f WHERE {PLAYED}").fetchone()["s"]


def _season(conn: Connection, season: str | None) -> str:
    """Default a missing season argument to the current season."""
    return season or current_season(conn)


def _unresolved(kind: str, name: str, lookup: Lookup) -> dict:
    """Build the error payload for a name that matched nothing, or matched several candidates."""
    if not lookup.candidates:
        return {"error": f"No {kind} found matching '{name}'."}
    fields = ("name", "teams", "position", "last_season", "appearances", "is_coach")
    return {
        "error": f"'{name}' matches several {kind}s — ask which one, or pass the team.",
        "candidates": [clean({k: c[k] for k in fields if k in c}) for c in lookup.candidates],
    }


def incomplete_seasons(conn: Connection, seasons: set[str]) -> list[str]:
    """Seasons whose lineups/goals are only partly loaded — per-player numbers there are too low."""
    if not seasons:
        return []
    rows = conn.execute(
        f"""
        SELECT season FROM fixtures f WHERE season = ANY(%s) AND f.status = 'FINISHED'  -- awarded matches have no details
        GROUP BY season HAVING bool_or(NOT details_fetched) ORDER BY season DESC
        """,
        (list(seasons),),
    ).fetchall()
    return [r["season"] for r in rows]


def matches_missing_goals(conn: Connection, seasons: set[str]) -> dict[str, int]:
    """Per season: loaded matches whose goal events from the provider don't add up to the score."""
    if not seasons:
        return {}
    rows = conn.execute(
        """
        SELECT season, count(*) AS n FROM fixtures
        WHERE season = ANY(%s) AND details_fetched AND goals_complete = false
        GROUP BY season
        """,
        (list(seasons),),
    ).fetchall()
    return {r["season"]: r["n"] for r in rows}


def _with_coverage_warning(conn: Connection, result: dict, seasons: set[str]) -> dict:
    """Attach warnings to `result` if any of `seasons` is partly loaded or has provider gaps."""
    warnings = []
    missing = incomplete_seasons(conn, seasons)
    if missing:
        warnings.append(f"Match details are only partly loaded for {', '.join(missing)}: "
                        "goals/assists/appearances for those seasons are incomplete. Do not draw "
                        "conclusions from them.")
    gaps = matches_missing_goals(conn, seasons)
    if gaps:
        detail = ", ".join(f"{n} in {season}" for season, n in sorted(gaps.items(), reverse=True))
        warnings.append(f"The data provider is missing goal details for some matches ({detail}); "
                        "goal and assist totals may be slightly low.")
    if warnings:
        result["warning"] = " ".join(warnings)
    return result


def _team(conn: Connection, name: str) -> tuple[dict | None, dict | None]:
    """Resolve a team name. Returns (team_row, None) on success or (None, error_payload)."""
    lookup = find_team(conn, name)
    return (lookup.match, None) if lookup.match else (None, _unresolved("team", name, lookup))


# --------------------------------------------------------------------------- coverage

def data_coverage(conn: Connection) -> dict:
    """Tool: which seasons/matches exist and what the data can't answer. Keeps pundits honest."""
    rows = conn.execute(
        f"""
        SELECT season,
               count(*) FILTER (WHERE {PLAYED}) AS matches_played,
               count(*) FILTER (WHERE {PLAYED} AND details_fetched) AS matches_with_details,
               count(*) FILTER (WHERE details_fetched AND goals_complete = false) AS matches_missing_goal_details,
               max(round) FILTER (WHERE {PLAYED}) AS last_round_played,
               max(kickoff_utc) FILTER (WHERE {PLAYED}) AS last_match_date
        FROM fixtures f GROUP BY season HAVING count(*) >= 100 ORDER BY season DESC
        """
    ).fetchall()
    return clean({
        "league": "Ligat Ha'Al (Israeli Premier League)",
        "current_season": current_season(conn),
        "seasons": rows,
        "limitations": [
            "Only seasons listed here exist. Anything earlier (e.g. all-time records) is NOT in the data.",
            "Lineups, goals and match stats exist only for matches_with_details.",
            "For matches_missing_goal_details the provider sent fewer goal events than the final score, "
            "so per-player goal/assist totals can be slightly low.",
            "Goal events have scorer, assist, minute and penalty flag. No cards/substitution events per player.",
            "No minutes played: appearances are counted as starts and bench appearances (a listed substitute "
            "may not have entered the game).",
            "No player-level stats beyond goals and assists (no shots, passes or ratings per player).",
        ],
    })


# --------------------------------------------------------------------------- league

def league_table(conn: Connection, season: str | None = None, venue: str = "all",
                 up_to_round: int | None = None) -> dict:
    """Tool: league table computed from results, overall or home/away, optionally after a given round."""
    season = _season(conn, season)
    sides = {
        "all": ("home", "away"),
        "home": ("home",),
        "away": ("away",),
    }[venue]
    parts = []
    if "home" in sides:
        parts.append("SELECT f.home_team_id AS team_id, f.home_score AS gf, f.away_score AS ga FROM fixtures f "
                     f"WHERE f.season = %(s)s AND {PLAYED} AND (%(r)s::int IS NULL OR f.round <= %(r)s)")
    if "away" in sides:
        parts.append("SELECT f.away_team_id AS team_id, f.away_score AS gf, f.home_score AS ga FROM fixtures f "
                     f"WHERE f.season = %(s)s AND {PLAYED} AND (%(r)s::int IS NULL OR f.round <= %(r)s)")
    rows = conn.execute(
        f"""
        WITH r AS ({' UNION ALL '.join(parts)})
        SELECT t.name AS team, count(*) AS played,
               sum((gf > ga)::int) AS won, sum((gf = ga)::int) AS drawn, sum((gf < ga)::int) AS lost,
               sum(gf) AS goals_for, sum(ga) AS goals_against, sum(gf - ga) AS goal_diff,
               sum(CASE WHEN gf > ga THEN 3 WHEN gf = ga THEN 1 ELSE 0 END) AS points
        FROM r JOIN teams t ON t.id = r.team_id
        GROUP BY t.name
        ORDER BY points DESC, goal_diff DESC, goals_for DESC, t.name
        """,
        {"s": season, "r": up_to_round},
    ).fetchall()
    for i, row in enumerate(rows, 1):
        row["position"] = i
    return clean({"season": season, "venue": venue, "up_to_round": up_to_round, "table": rows,
                  "note": "Computed from match results. Ignores any point deductions and playoff split rules."})


def top_scorers(conn: Connection, season: str | None = None, team: str | None = None,
                rank_by: str = "goals", limit: int = 10) -> dict:
    """Tool: ranking by goals, assists or goals+assists for a season, optionally within one team."""
    season = _season(conn, season)
    team_row = None
    if team:
        team_row, err = _team(conn, team)
        if err:
            return err
    # ORDER BY can use an output alias alone, but not inside an expression, hence the sums.
    order = {"goals": "sum(goal)", "assists": "sum(assist)", "goal_contributions": "sum(goal) + sum(assist)"}[rank_by]
    rows = conn.execute(
        f"""
        WITH contrib AS (
            SELECT g.scorer_key AS key, g.team_id, 1 AS goal, 0 AS assist, (g.info = 'Penalty')::int AS pen
            FROM goals g JOIN fixtures f ON f.id = g.fixture_id
            WHERE f.season = %(s)s AND g.scorer_key IS NOT NULL
            UNION ALL
            SELECT g.assist_key, g.team_id, 0, 1, 0
            FROM goals g JOIN fixtures f ON f.id = g.fixture_id
            WHERE f.season = %(s)s AND g.assist_key IS NOT NULL
        )
        SELECT p.display_name AS player, t.name AS team,
               sum(goal) AS goals, sum(pen) AS penalty_goals, sum(assist) AS assists
        FROM contrib c JOIN players p ON p.key = c.key JOIN teams t ON t.id = c.team_id
        WHERE (%(t)s::text IS NULL OR c.team_id = %(t)s)
        GROUP BY p.key, p.display_name, t.name
        HAVING sum(goal) + sum(assist) > 0
        ORDER BY {order} DESC, sum(goal) DESC, sum(assist) DESC, player
        LIMIT %(n)s
        """,
        {"s": season, "t": team_row["id"] if team_row else None, "n": min(limit, 50)},
    ).fetchall()
    return clean(_with_coverage_warning(conn, {"season": season, "team": team_row["name"] if team_row else None,
                                               "rank_by": rank_by, "players": rows}, {season}))


# --------------------------------------------------------------------------- players

def player_stats(conn: Connection, player: str, season: str | None = None, team: str | None = None) -> dict:
    """Tool: one player's (or coach's) record per season and team: starts, bench listings, goals, assists."""
    team_row = None
    if team:
        team_row, err = _team(conn, team)
        if err:
            return err
    lookup = find_player(conn, player, team_row["id"] if team_row else None)
    if not lookup.match:
        return _unresolved("player", player, lookup)
    p = lookup.match

    rows = conn.execute(
        """
        WITH apps AS (
            SELECT f.season, l.team_id,
                   count(*) FILTER (WHERE l.role = 'starter')    AS starts,
                   count(*) FILTER (WHERE l.role = 'substitute') AS on_bench,
                   count(*) FILTER (WHERE l.role = 'coach')      AS matches_as_coach
            FROM lineups l JOIN fixtures f ON f.id = l.fixture_id
            WHERE l.player_key = %(k)s GROUP BY 1, 2
        ), g AS (
            SELECT f.season, g.team_id,
                   count(*) FILTER (WHERE g.scorer_key = %(k)s) AS goals,
                   count(*) FILTER (WHERE g.scorer_key = %(k)s AND g.info = 'Penalty') AS penalty_goals,
                   count(*) FILTER (WHERE g.assist_key = %(k)s) AS assists
            FROM goals g JOIN fixtures f ON f.id = g.fixture_id
            WHERE %(k)s IN (g.scorer_key, g.assist_key) GROUP BY 1, 2
        )
        SELECT coalesce(a.season, g.season) AS season, t.name AS team,
               coalesce(a.starts, 0) AS starts, coalesce(a.on_bench, 0) AS listed_as_substitute,
               coalesce(a.matches_as_coach, 0) AS matches_as_coach,
               coalesce(g.goals, 0) AS goals, coalesce(g.penalty_goals, 0) AS penalty_goals,
               coalesce(g.assists, 0) AS assists
        FROM apps a FULL JOIN g ON g.season = a.season AND g.team_id = a.team_id
        JOIN teams t ON t.id = coalesce(a.team_id, g.team_id)
        WHERE %(s)s::text IS NULL OR coalesce(a.season, g.season) = %(s)s
        ORDER BY season DESC
        """,
        {"k": p["key"], "s": season},
    ).fetchall()
    return clean(_with_coverage_warning(conn, {
        "player": p["name"], "position": p["position"], "seasons": rows,
        "note": "listed_as_substitute counts bench listings; the data does not say if he came on.",
    }, {r["season"] for r in rows}))


# --------------------------------------------------------------------------- teams

def _match_rows(conn: Connection, where: str, params: dict, limit: int) -> list[dict]:
    """Played matches matching a WHERE clause, newest first (shared by team_form and head_to_head)."""
    return conn.execute(
        f"""
        SELECT f.kickoff_utc AS date, f.season, f.round, h.name AS home, a.name AS away,
               f.home_score, f.away_score, f.home_ht_score, f.away_ht_score, f.home_team_id, f.away_team_id
        FROM fixtures f JOIN teams h ON h.id = f.home_team_id JOIN teams a ON a.id = f.away_team_id
        WHERE {PLAYED} AND {where}
        ORDER BY f.kickoff_utc DESC LIMIT %(limit)s
        """,
        {**params, "limit": limit},
    ).fetchall()


def _result_for(team_id: str, m: dict) -> str:
    """W / D / L from the point of view of `team_id`."""
    gf, ga = (m["home_score"], m["away_score"]) if m["home_team_id"] == team_id else (m["away_score"], m["home_score"])
    return "W" if gf > ga else "D" if gf == ga else "L"


def team_form(conn: Connection, team: str, last_n: int = 5, venue: str = "all") -> dict:
    """Tool: a team's last N results, as a W/D/L string plus goals for/against."""
    team_row, err = _team(conn, team)
    if err:
        return err
    tid = team_row["id"]
    where = {"all": "%(t)s IN (f.home_team_id, f.away_team_id)",
             "home": "f.home_team_id = %(t)s", "away": "f.away_team_id = %(t)s"}[venue]
    matches = _match_rows(conn, where, {"t": tid}, min(last_n, 40))
    results = [_result_for(tid, m) for m in matches]
    gf = sum(m["home_score"] if m["home_team_id"] == tid else m["away_score"] for m in matches)
    ga = sum(m["away_score"] if m["home_team_id"] == tid else m["home_score"] for m in matches)
    for m, r in zip(matches, results):
        m["result"] = r
        del m["home_team_id"], m["away_team_id"]
    return clean({
        "team": team_row["name"], "venue": venue,
        "form": "".join(results),  # most recent first
        "summary": {"won": results.count("W"), "drawn": results.count("D"), "lost": results.count("L"),
                    "goals_for": gf, "goals_against": ga},
        "matches": matches,
    })


def head_to_head(conn: Connection, team_a: str, team_b: str, limit: int = 10) -> dict:
    """Tool: recent meetings between two teams and a win/draw/loss summary."""
    a, err = _team(conn, team_a)
    if err:
        return err
    b, err = _team(conn, team_b)
    if err:
        return err
    matches = _match_rows(
        conn,
        "((f.home_team_id = %(a)s AND f.away_team_id = %(b)s) OR (f.home_team_id = %(b)s AND f.away_team_id = %(a)s))",
        {"a": a["id"], "b": b["id"]}, min(limit, 40),
    )
    results = [_result_for(a["id"], m) for m in matches]
    for m in matches:
        del m["home_team_id"], m["away_team_id"]
    return clean({
        "team_a": a["name"], "team_b": b["name"],
        "summary": {f"{a['name']} wins": results.count("W"), "draws": results.count("D"),
                    f"{b['name']} wins": results.count("L")},
        "matches": matches,
    })


def team_match_stats(conn: Connection, team: str, season: str | None = None) -> dict:
    """Per-match averages of shots, possession, corners... for the team and its opponents."""
    season = _season(conn, season)
    team_row, err = _team(conn, team)
    if err:
        return err
    rows = conn.execute(
        f"""
        SELECT s.stat,
               round(avg(s.value) FILTER (WHERE s.team_id = %(t)s), 2)  AS team_avg,
               round(avg(s.value) FILTER (WHERE s.team_id <> %(t)s), 2) AS opponents_avg,
               count(DISTINCT s.fixture_id) AS matches
        FROM match_stats s JOIN fixtures f ON f.id = s.fixture_id
        WHERE f.season = %(s)s AND {PLAYED} AND %(t)s IN (f.home_team_id, f.away_team_id)
        GROUP BY s.stat ORDER BY s.stat
        """,
        {"t": team_row["id"], "s": season},
    ).fetchall()
    return clean(_with_coverage_warning(conn, {"team": team_row["name"], "season": season, "per_match": rows,
                  "note": "Provider stats; some fields are known to be inconsistent (e.g. On Target vs Shots On Goal)."},
                  {season}))


# --------------------------------------------------------------------------- matches

def match_report(conn: Connection, team_a: str, team_b: str | None = None,
                 season: str | None = None, round: int | None = None) -> dict:
    """The most recent played match of team_a (optionally vs team_b / in a given season or round)."""
    a, err = _team(conn, team_a)
    if err:
        return err
    b = None
    if team_b:
        b, err = _team(conn, team_b)
        if err:
            return err
    fixture = conn.execute(
        f"""
        SELECT f.*, h.name AS home, aw.name AS away
        FROM fixtures f JOIN teams h ON h.id = f.home_team_id JOIN teams aw ON aw.id = f.away_team_id
        WHERE {PLAYED} AND %(a)s IN (f.home_team_id, f.away_team_id)
          AND (%(b)s::text IS NULL OR %(b)s IN (f.home_team_id, f.away_team_id))
          AND (%(s)s::text IS NULL OR f.season = %(s)s)
          AND (%(r)s::int IS NULL OR f.round = %(r)s)
        ORDER BY f.kickoff_utc DESC LIMIT 1
        """,
        {"a": a["id"], "b": b["id"] if b else None, "s": season, "r": round},
    ).fetchone()
    if not fixture:
        return {"error": "No played match found with those filters."}
    fid = fixture["id"]
    side = {fixture["home_team_id"]: "home", fixture["away_team_id"]: "away"}

    report = {
        "date": fixture["kickoff_utc"], "season": fixture["season"], "round": fixture["round"],
        "stadium": fixture["stadium"], "referee": fixture["referee"],
        "home": fixture["home"], "away": fixture["away"],
        "score": f"{fixture['home_score']}-{fixture['away_score']}",
        "half_time": f"{fixture['home_ht_score']}-{fixture['away_ht_score']}",
        "formations": {"home": fixture["home_formation"], "away": fixture["away_formation"]},
        "details_available": fixture["details_fetched"],
    }
    if not fixture["details_fetched"]:
        return clean(report)

    report["goals"] = conn.execute(
        """
        SELECT g.minute_text AS minute, t.name AS team, coalesce(ps.display_name, g.scorer_name) AS scorer,
               coalesce(pa.display_name, g.assist_name) AS assist, g.info
        FROM goals g JOIN teams t ON t.id = g.team_id
        LEFT JOIN players ps ON ps.key = g.scorer_key LEFT JOIN players pa ON pa.key = g.assist_key
        WHERE g.fixture_id = %s ORDER BY g.minute
        """,
        (fid,),
    ).fetchall()

    lineups = {"home": {"starters": [], "substitutes": [], "coach": None},
               "away": {"starters": [], "substitutes": [], "coach": None}}
    for row in conn.execute(
        """
        SELECT l.team_id, l.role, l.shirt_number, p.display_name, p.position
        FROM lineups l JOIN players p ON p.key = l.player_key
        WHERE l.fixture_id = %s ORDER BY l.role, l.shirt_number
        """,
        (fid,),
    ):
        entry = lineups[side[row["team_id"]]]
        if row["role"] == "coach":
            entry["coach"] = row["display_name"]
        else:
            key = "starters" if row["role"] == "starter" else "substitutes"
            entry[key].append({"name": row["display_name"], "number": row["shirt_number"],
                               "position": row["position"]})
    report["lineups"] = lineups

    stats: dict[str, dict] = {}
    for row in conn.execute("SELECT team_id, stat, value FROM match_stats WHERE fixture_id = %s", (fid,)):
        stats.setdefault(row["stat"], {})[side[row["team_id"]]] = row["value"]
    report["stats"] = stats
    return clean(report)
