-- Two layers:
--   raw.*  — API responses exactly as received. Lets us re-normalize without spending quota,
--            and keeps an audit trail of where every number came from.
--   public — normalized tables the agents query.
-- Idempotent: safe to run on every startup.

CREATE SCHEMA IF NOT EXISTS raw;

-- Name search: accent-insensitive ('Davó' = 'Davo') and typo-tolerant (trigram similarity).
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS raw.api_responses (
    source      text        NOT NULL,              -- 'goal_api' | 'api_football'
    endpoint    text        NOT NULL,              -- path + sorted query string
    status_code int         NOT NULL,
    payload     jsonb       NOT NULL,
    fetched_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, endpoint)
);

CREATE TABLE IF NOT EXISTS teams (
    id        text PRIMARY KEY,                    -- Goal API team id
    name      text NOT NULL,
    badge_url text
);

CREATE TABLE IF NOT EXISTS players (
    key          text PRIMARY KEY,                 -- Goal API playerKey (shared by lineups and events)
    name         text NOT NULL,                    -- 'Omer Atzili', or abbreviated 'E. Sokler' for many foreigners
    -- What the pundits call a player: 'E. Sokler' -> 'Sokler'. Full names stay as-is.
    display_name text GENERATED ALWAYS AS (regexp_replace(name, '^[A-Z]\.\s*', '')) STORED,
    position     text,                             -- Goalkeepers / Defenders / Midfielders / Forwards
    image_url    text
);

-- The API gives some players several keys; see app/ingest/players.py.
CREATE TABLE IF NOT EXISTS player_aliases (
    alias_key     text PRIMARY KEY,
    canonical_key text NOT NULL
);

CREATE TABLE IF NOT EXISTS fixtures (
    id              text PRIMARY KEY,
    season          text        NOT NULL,          -- '2026/2027'
    round           int,
    stage           text,                          -- as given by the API; inconsistent across seasons
    kickoff_utc     timestamptz NOT NULL,
    status          text        NOT NULL,          -- FINISHED / SCHEDULED / AWARDED ...
    home_team_id    text        NOT NULL REFERENCES teams(id),
    away_team_id    text        NOT NULL REFERENCES teams(id),
    home_score      int,
    away_score      int,
    home_ht_score   int,
    away_ht_score   int,
    home_formation  text,
    away_formation  text,
    stadium         text,
    referee         text,
    details_fetched boolean     NOT NULL DEFAULT false   -- lineups/goals/stats loaded
);
CREATE INDEX IF NOT EXISTS fixtures_season_idx ON fixtures (season);
CREATE INDEX IF NOT EXISTS fixtures_home_idx   ON fixtures (home_team_id);
CREATE INDEX IF NOT EXISTS fixtures_away_idx   ON fixtures (away_team_id);
-- false when the provider's goal events don't add up to the final score (e.g. it sent none at all)
ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS goals_complete boolean;

CREATE TABLE IF NOT EXISTS lineups (
    fixture_id   text NOT NULL REFERENCES fixtures(id) ON DELETE CASCADE,
    team_id      text NOT NULL REFERENCES teams(id),
    player_key   text NOT NULL REFERENCES players(key),
    role         text NOT NULL CHECK (role IN ('starter', 'substitute', 'coach')),
    shirt_number int,
    PRIMARY KEY (fixture_id, player_key)
);
CREATE INDEX IF NOT EXISTS lineups_player_idx ON lineups (player_key);

-- The API only reports goals (no cards/substitution events).
CREATE TABLE IF NOT EXISTS goals (
    id          text PRIMARY KEY,
    fixture_id  text NOT NULL REFERENCES fixtures(id) ON DELETE CASCADE,
    team_id     text NOT NULL REFERENCES teams(id),
    minute      int,                               -- numeric minute (stoppage time folded in)
    minute_text text,                              -- as given, e.g. '90+3'
    scorer_key  text REFERENCES players(key),
    scorer_name text,
    assist_key  text REFERENCES players(key),
    assist_name text,
    info        text                               -- e.g. 'Penalty', 'Own Goal' when provided
);
CREATE INDEX IF NOT EXISTS goals_fixture_idx ON goals (fixture_id);
CREATE INDEX IF NOT EXISTS goals_scorer_idx  ON goals (scorer_key);

-- Long format: one row per stat per team, so new stat types need no migration.
CREATE TABLE IF NOT EXISTS match_stats (
    fixture_id text    NOT NULL REFERENCES fixtures(id) ON DELETE CASCADE,
    team_id    text    NOT NULL REFERENCES teams(id),
    stat       text    NOT NULL,                   -- 'Shots Total', 'Ball Possession', ...
    value      numeric,                            -- '50%' stored as 50
    PRIMARY KEY (fixture_id, team_id, stat)
);

-- Tables are dropped on --rebuild, so re-grant the read-only role (db/readonly_role.sql) if it exists.
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'pundit_ro') THEN
        GRANT SELECT ON teams, players, fixtures, lineups, goals, match_stats TO pundit_ro;
    END IF;
END $$;
