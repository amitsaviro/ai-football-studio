"""Tool definitions in the shape the Claude Messages API expects, plus a dispatcher."""

import json
import logging
from collections.abc import Callable

from app.db import connect
from app.tools import sql, stats

log = logging.getLogger(__name__)

SEASON = {"type": "string", "description": "Season like '2026/2027'. Omit for the current season."}
TEAM = {"type": "string", "description": "Team name in English or Hebrew, e.g. 'Maccabi Haifa' or 'מכבי חיפה'."}
VENUE = {"type": "string", "enum": ["all", "home", "away"], "description": "Default 'all'."}

TOOLS: list[dict] = [
    {
        "name": "data_coverage",
        "description": "Which seasons and matches exist in the database, and what the data does NOT contain. "
                       "Call this before answering questions about history, records or anything unusual.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "league_table",
        "description": "League table computed from results. Supports home/away tables and the table after a given round.",
        "input_schema": {"type": "object", "properties": {
            "season": SEASON, "venue": VENUE,
            "up_to_round": {"type": "integer", "description": "Table as it stood after this round."},
        }},
    },
    {
        "name": "top_scorers",
        "description": "Top scorers / assisters / goal contributions for a season, optionally within one team. "
                       "Includes penalty goals.",
        "input_schema": {"type": "object", "properties": {
            "season": SEASON, "team": TEAM,
            "rank_by": {"type": "string", "enum": ["goals", "assists", "goal_contributions"]},
            "limit": {"type": "integer", "description": "Default 10, max 50."},
        }},
    },
    {
        "name": "player_stats",
        "description": "A player's (or coach's) record per season and team: starts, bench listings, goals, "
                       "penalty goals, assists. Accepts full name or surname; returns candidates if ambiguous.",
        "input_schema": {"type": "object", "properties": {
            "player": {"type": "string", "description": "In English letters, e.g. 'Dor Peretz' or 'Peretz' "
                                                       "(transliterate Hebrew names: פרץ -> Peretz)."},
            "season": SEASON, "team": {**TEAM, "description": "Use to disambiguate players with the same name."},
        }, "required": ["player"]},
    },
    {
        "name": "team_form",
        "description": "A team's most recent results (W/D/L), goals for/against.",
        "input_schema": {"type": "object", "properties": {
            "team": TEAM, "venue": VENUE,
            "last_n": {"type": "integer", "description": "Default 5, max 40."},
        }, "required": ["team"]},
    },
    {
        "name": "head_to_head",
        "description": "Recent matches between two teams and the win/draw/loss summary.",
        "input_schema": {"type": "object", "properties": {
            "team_a": TEAM, "team_b": TEAM,
            "limit": {"type": "integer", "description": "Default 10, max 40."},
        }, "required": ["team_a", "team_b"]},
    },
    {
        "name": "team_match_stats",
        "description": "A team's per-match averages for a season (shots, shots on goal, possession, corners, "
                       "fouls, cards, saves...) next to its opponents' averages. Good for style of play questions.",
        "input_schema": {"type": "object", "properties": {"team": TEAM, "season": SEASON}, "required": ["team"]},
    },
    {
        "name": "match_report",
        "description": "Full report of one played match: score, goals with scorers/assists, lineups, coaches, "
                       "formations and team stats. Defaults to the team's most recent match.",
        "input_schema": {"type": "object", "properties": {
            "team_a": TEAM, "team_b": {**TEAM, "description": "Opponent, to pick a specific fixture."},
            "season": SEASON, "round": {"type": "integer"},
        }, "required": ["team_a"]},
    },
    {
        "name": "run_sql",
        "description": "Run one read-only SELECT query for questions the other tools don't cover. "
                       "Max 100 rows, 3s timeout.\n" + sql.SCHEMA_DOC,
        "input_schema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "A single PostgreSQL SELECT or WITH query."},
        }, "required": ["query"]},
    },
]

_HANDLERS: dict[str, Callable] = {
    "data_coverage": stats.data_coverage,
    "league_table": stats.league_table,
    "top_scorers": stats.top_scorers,
    "player_stats": stats.player_stats,
    "team_form": stats.team_form,
    "head_to_head": stats.head_to_head,
    "team_match_stats": stats.team_match_stats,
    "match_report": stats.match_report,
}


def call_tool(name: str, args: dict) -> dict:
    """Run a tool by name. Errors are returned as data so the model can recover."""
    try:
        if name == "run_sql":
            return sql.run_sql(**args)
        handler = _HANDLERS.get(name)
        if handler is None:
            return {"error": f"Unknown tool '{name}'."}
        with connect() as conn:
            return handler(conn, **args)
    except TypeError as e:  # bad/missing arguments from the model
        return {"error": f"Invalid arguments for {name}: {e}"}
    except Exception as e:
        log.exception("Tool %s failed", name)
        return {"error": f"{name} failed: {type(e).__name__}"}


def call_tool_json(name: str, args: dict) -> str:
    """call_tool, serialized for a tool_result message (keeps Hebrew readable)."""
    return json.dumps(call_tool(name, args), ensure_ascii=False)
