-- Role used by the run_sql tool: the LLM writes SQL, the database enforces what it may do.
-- Run as a superuser:  psql -d football -f db/readonly_role.sql
-- In production, also set a password: ALTER ROLE pundit_ro PASSWORD '...';

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pundit_ro') THEN
        CREATE ROLE pundit_ro LOGIN;
    END IF;
END $$;

ALTER ROLE pundit_ro SET default_transaction_read_only = on;
ALTER ROLE pundit_ro SET statement_timeout = '3s';
ALTER ROLE pundit_ro SET search_path = public;
ALTER ROLE pundit_ro CONNECTION LIMIT 5;

REVOKE ALL ON SCHEMA raw FROM pundit_ro;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE football TO pundit_ro;
GRANT USAGE ON SCHEMA public TO pundit_ro;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pundit_ro;
GRANT SELECT ON teams, players, fixtures, lineups, goals, match_stats TO pundit_ro;
