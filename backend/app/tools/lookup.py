"""Resolve free-text team/player names (English or Hebrew, typos, accents) to DB ids.

A lookup returns either a single match or a list of candidates, so the agent can ask
for clarification instead of guessing between two players with the same surname.
"""

from dataclasses import dataclass

from psycopg import Connection

# Hebrew names and common nicknames -> team name in the DB.
TEAM_ALIASES = {
    "מכבי תל אביב": "Maccabi Tel Aviv", "מכבי ת״א": "Maccabi Tel Aviv", "מכבי תא": "Maccabi Tel Aviv",
    "מכבי חיפה": "Maccabi Haifa",
    "הפועל תל אביב": "Hapoel Tel Aviv", "הפועל ת״א": "Hapoel Tel Aviv", "הפועל תא": "Hapoel Tel Aviv",
    "הפועל באר שבע": "Hapoel Be'er Sheva", "באר שבע": "Hapoel Be'er Sheva", "הפועל ב״ש": "Hapoel Be'er Sheva",
    "בית״ר ירושלים": "Beitar Jerusalem", "ביתר ירושלים": "Beitar Jerusalem", "בית״ר": "Beitar Jerusalem",
    "ביתר": "Beitar Jerusalem",
    "הפועל ירושלים": "Hapoel Jerusalem",
    "הפועל חיפה": "Hapoel Haifa",
    "בני סכנין": "Bnei Sakhnin", "סכנין": "Bnei Sakhnin",
    "מכבי נתניה": "Maccabi Netanya", "נתניה": "Maccabi Netanya",
    "הפועל פתח תקווה": "Hapoel Petah Tikva", "הפועל פ״ת": "Hapoel Petah Tikva",
    "מכבי פתח תקווה": "Maccabi Petah Tikva", "מכבי פ״ת": "Maccabi Petah Tikva",
    "הפועל רמת גן": "Hapoel Ramat Gan",
    "עירוני קריית שמונה": "Ironi Kiryat Shmona", "קריית שמונה": "Ironi Kiryat Shmona",
    "עירוני טבריה": "Ironi Tiberias", "טבריה": "Ironi Tiberias",
    "אשדוד": "Ashdod", "מ.ס. אשדוד": "Ashdod",
    "בני יהודה": "Bnei Yehuda",
    "הפועל חדרה": "Hapoel Hadera", "חדרה": "Hapoel Hadera",
    "מכבי בני ריינה": "Maccabi Bnei Raina", "בני ריינה": "Maccabi Bnei Raina",
    "הפועל כפר סבא": "Hapoel Kfar Saba",
    "הפועל נוף הגליל": "Hapoel Nof HaGalil",
    "סקציה נס ציונה": "Sektzia Nes Tziona",
    "הפועל רעננה": "Hapoel Ra'anana",
    "הפועל עכו": "Hapoel Acre",
}


@dataclass
class Lookup:
    """Result of a name search: `match` when exactly one row fits, otherwise the candidates."""
    match: dict | None          # the single resolved row, if unambiguous
    candidates: list[dict]      # all plausible rows (for clarification / error messages)

    @property
    def ambiguous(self) -> bool:
        """True when several rows fit and none clearly wins."""
        return self.match is None and len(self.candidates) > 1


def _normalize(text: str) -> str:
    """Treat an ASCII double quote like gershayim, so 'פ"ת' matches the alias 'פ״ת'."""
    return text.strip().replace('"', "״")


def find_team(conn: Connection, name: str) -> Lookup:
    """Resolve a team name: Hebrew alias table first, then exact / substring / trigram-similarity match."""
    query = TEAM_ALIASES.get(_normalize(name), name.strip())
    rows = conn.execute(
        """
        SELECT id, name,
               CASE WHEN lower(unaccent(name)) = lower(unaccent(%(q)s)) THEN 1.0
                    ELSE similarity(lower(unaccent(name)), lower(unaccent(%(q)s))) END AS score
        FROM teams
        WHERE lower(unaccent(name)) = lower(unaccent(%(q)s))
           OR lower(unaccent(name)) LIKE '%%' || lower(unaccent(%(q)s)) || '%%'
           OR similarity(lower(unaccent(name)), lower(unaccent(%(q)s))) > 0.3
        ORDER BY score DESC, name
        LIMIT 5
        """,
        {"q": query},
    ).fetchall()
    if not rows:
        return Lookup(None, [])
    if rows[0]["score"] == 1.0 or len(rows) == 1 or rows[0]["score"] - rows[1]["score"] > 0.2:
        return Lookup(rows[0], rows)
    return Lookup(None, rows)


def find_player(conn: Connection, name: str, team_id: str | None = None) -> Lookup:
    """Match on full name, surname ('Peretz'), abbreviated form ('D. Peretz') or fuzzy spelling.

    Each candidate comes with the teams he played for, so same-name players can be told apart.
    """
    rows = conn.execute(
        """
        WITH q AS (SELECT lower(unaccent(%(q)s)) AS q),
        scored AS (
            SELECT p.key, p.name, p.display_name, p.position,
                   CASE
                       WHEN lower(unaccent(p.name)) = q.q OR lower(unaccent(p.display_name)) = q.q THEN 1.0
                       -- surname only: 'peretz' matches 'Dor Peretz' and 'D. Peretz'
                       WHEN lower(unaccent(p.display_name)) LIKE '%% ' || q.q
                         OR lower(unaccent(p.name)) LIKE '%% ' || q.q THEN 0.9
                       ELSE similarity(lower(unaccent(p.name)), q.q)
                   END AS score
            FROM players p, q
        )
        SELECT s.key, s.name, s.display_name, s.position, s.score,
               array_agg(DISTINCT t.name) AS teams,
               max(f.season) AS last_season,
               count(DISTINCT l.fixture_id) FILTER (WHERE l.role <> 'coach') AS appearances,
               bool_or(l.role = 'coach') AS is_coach
        FROM scored s
        JOIN lineups l  ON l.player_key = s.key
        JOIN teams t    ON t.id = l.team_id
        JOIN fixtures f ON f.id = l.fixture_id
        WHERE s.score >= 0.45
          AND (%(team)s::text IS NULL OR l.team_id = %(team)s)
        GROUP BY s.key, s.name, s.display_name, s.position, s.score
        ORDER BY s.score DESC, appearances DESC
        LIMIT 8
        """,
        {"q": name.strip(), "team": team_id},
    ).fetchall()
    if not rows:
        return Lookup(None, [])
    top = rows[0]["score"]
    best = [r for r in rows if r["score"] == top]
    if len(best) == 1 and (len(rows) == 1 or top - rows[1]["score"] > 0.05 or top >= 0.9):
        return Lookup(best[0], rows)
    return Lookup(None, rows)
