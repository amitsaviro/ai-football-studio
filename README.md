# AI Football Studio

A panel of AI pundits that debates the Israeli Premier League (Ligat Ha'Al) live. Every claim is checked against real data that syncs automatically.

> Work in progress.

## Structure
```
backend/   FastAPI, LangGraph agents, data ingestion (Python)
frontend/  React + Vite UI
```

## Setup (backend)
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in keys
python scripts/check_coverage.py
```
