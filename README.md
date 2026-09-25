# AI Football Studio

A panel of AI pundits that debates the Israeli Premier League (Ligat Ha'Al) live. Every claim is checked against real data that syncs automatically.

> Work in progress. A Hebrew walkthrough of the codebase lives in [docs/GUIDE_HE.md](docs/GUIDE_HE.md).

## Structure
```
backend/
  app/sources/   API clients (Goal API) with a raw-response cache
  app/ingest/    normalization + player identity resolution
  app/tools/     the tools the pundits call: stats queries and sandboxed read-only SQL
  db/            schema.sql, readonly_role.sql
  scripts/       ingest.py, coverage probes
  tests/         integration tests (invariants + SQL security)
frontend/        React + Vite UI (not started)
```

## Setup (backend)
```bash
brew install postgresql@18 && brew services start postgresql@18
createdb football

cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                        # fill in API keys

python scripts/ingest.py                    # run daily: syncs fixtures + as many match details as the quota allows
psql -d football -f db/readonly_role.sql    # read-only role for the run_sql tool
pytest tests
```

## Data quality notes
The free data source has known problems. The pipeline works around them instead of trusting the provider's aggregates:
- **The top-scorers and standings endpoints are wrong or stale.** Tables and scorer lists are computed from raw results and goal events.
- **The same player can show up under several IDs.** For example, the lineup uses one key and the goal event another. `app/ingest/players.py` merges keys with compatible names at the same club that never appear in the same lineup.
- **Key `0` means "unknown player".** It's dropped rather than merged.
- **Some matches have no goal events at all.** `fixtures.goals_complete` flags them, and the tools warn that totals may be slightly low.
- **Some match stats contradict each other** (`On Target` vs `Shots On Goal`), and the tools say so.
