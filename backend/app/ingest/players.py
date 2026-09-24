"""Player identity resolution.

Goal API sometimes gives the same player several keys (e.g. one key when he starts, another
when he comes off the bench). Two keys are merged when:
  * their names are compatible ('Dor Peretz' == 'Dor Peretz', or 'D. Peretz' ~ 'Dor Peretz'),
  * they appeared for the same team (in any season),
  * and they were never both in the same fixture's lineup (then they are two different people).
Coaches go through the same rules.

Aliases are rewritten to one canonical key in lineups/goals and recorded in player_aliases.
Deterministic and idempotent — runs after every ingestion.
"""

import logging
import re
from collections import defaultdict

from psycopg import Connection

log = logging.getLogger(__name__)

INITIAL_RE = re.compile(r"^([A-Z])\.\s*(.+)$")


def split_name(name: str) -> tuple[str | None, str]:
    """'D. Peretz' -> ('D', 'peretz'); 'Dor Peretz' -> ('D', 'peretz'); 'Sambinha' -> (None, 'sambinha')."""
    name = name.strip()
    m = INITIAL_RE.match(name)
    if m:
        return m.group(1), m.group(2).lower()
    parts = name.split(maxsplit=1)
    if len(parts) == 1:
        return None, name.lower()
    return parts[0][0].upper(), parts[1].lower()


def names_compatible(a: str, b: str) -> bool:
    """True if two spellings can be the same person: equal ignoring case, or same surname and first initial."""
    if a.lower() == b.lower():
        return True
    (ia, sa), (ib, sb) = split_name(a), split_name(b)
    return sa == sb and ia is not None and ia == ib


def is_abbreviated(name: str) -> bool:
    """True for provider-abbreviated names like 'E. Sokler'."""
    return bool(INITIAL_RE.match(name.strip()))


class UnionFind:
    """Minimal disjoint-set structure: groups keys that turn out to be the same player."""
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        """Return the group representative of x (with path compression)."""
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x


def resolve_players(conn: Connection) -> int:
    """Merge duplicate player keys into one canonical key (rules in the module docstring).

    Rewrites lineups/goals to the canonical key, records aliases, deletes alias rows.
    Returns the number of alias keys merged.
    """
    rows = conn.execute(
        """
        SELECT l.player_key, p.name, l.team_id, l.fixture_id, true AS in_lineup
        FROM lineups l
        JOIN players p  ON p.key = l.player_key
        UNION ALL
        -- Goal events sometimes use a different key than the lineup for the same player,
        -- so they count for team/season membership but not as a lineup appearance.
        SELECT k.key, p.name, g.team_id, g.fixture_id, false
        FROM goals g
        CROSS JOIN LATERAL (VALUES (g.scorer_key), (g.assist_key)) AS k(key)
        JOIN players p  ON p.key = k.key
        WHERE k.key IS NOT NULL
        """
    ).fetchall()

    name_of: dict[str, str] = {}
    fixtures_of: dict[str, set[str]] = defaultdict(set)
    appearances: dict[str, int] = defaultdict(int)
    by_team: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        key = r["player_key"]
        name_of[key] = r["name"]
        if r["in_lineup"]:
            fixtures_of[key].add(r["fixture_id"])
            appearances[key] += 1
        by_team[r["team_id"]].add(key)

    uf = UnionFind()
    group_fixtures = {key: set(fixtures_of[key]) for key in name_of}  # keyed by group root

    for keys in by_team.values():
        keys = sorted(keys)
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                ra, rb = uf.find(a), uf.find(b)
                if ra == rb or not names_compatible(name_of[a], name_of[b]):
                    continue
                if group_fixtures[ra] & group_fixtures[rb]:
                    continue  # played in the same match -> different people
                uf.parent[ra] = rb
                group_fixtures[rb] |= group_fixtures.pop(ra)

    groups: dict[str, list[str]] = defaultdict(list)
    for key in name_of:
        groups[uf.find(key)].append(key)

    merged = 0
    for keys in groups.values():
        if len(keys) < 2:
            continue
        # Canonical = most appearances; name = the fullest (non-abbreviated) spelling.
        canonical = max(keys, key=lambda k: (appearances[k], k))
        best_name = max((name_of[k] for k in keys), key=lambda n: (not is_abbreviated(n), len(n)))
        conn.execute("UPDATE players SET name = %s WHERE key = %s", (best_name, canonical))
        for alias in keys:
            if alias == canonical:
                continue
            conn.execute(
                """
                INSERT INTO player_aliases (alias_key, canonical_key) VALUES (%s, %s)
                ON CONFLICT (alias_key) DO UPDATE SET canonical_key = EXCLUDED.canonical_key
                """,
                (alias, canonical),
            )
            conn.execute(
                """
                UPDATE players c SET
                    position  = COALESCE(c.position, a.position),
                    image_url = COALESCE(c.image_url, a.image_url)
                FROM players a WHERE c.key = %s AND a.key = %s
                """,
                (canonical, alias),
            )
            conn.execute("UPDATE lineups SET player_key = %s WHERE player_key = %s", (canonical, alias))
            conn.execute("UPDATE goals SET scorer_key = %s WHERE scorer_key = %s", (canonical, alias))
            conn.execute("UPDATE goals SET assist_key = %s WHERE assist_key = %s", (canonical, alias))
            conn.execute("DELETE FROM players WHERE key = %s", (alias,))
            merged += 1

    conn.commit()
    log.info("Player resolution: %d alias keys merged", merged)
    return merged
