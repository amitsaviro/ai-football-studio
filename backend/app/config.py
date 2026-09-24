"""Application settings, read once from backend/.env.

Everything configurable (DB URLs, API keys, which Claude model the pundits use) lives here,
so the rest of the code never reads environment variables directly.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@dataclass(frozen=True)
class Settings:
    """Immutable settings object; import the shared `settings` instance below."""
    database_url: str = os.getenv("DATABASE_URL", "postgresql:///football")
    # Read-only role for LLM-written SQL (db/readonly_role.sql)
    database_url_readonly: str = os.getenv("DATABASE_URL_READONLY", "postgresql://pundit_ro@/football")
    goal_api_key: str = os.getenv("GOAL_API_KEY", "")
    api_football_key: str = os.getenv("API_FOOTBALL_KEY", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    pundit_model: str = os.getenv("PUNDIT_MODEL", "claude-opus-5")
    # low | medium | high | xhigh | max — how hard the model thinks; the main cost lever
    pundit_effort: str = os.getenv("PUNDIT_EFFORT", "medium")

    # Goal API id of Ligat Ha'al
    goal_league_id: str = "cmr77dwbc00i0rx06adepi1hb"


settings = Settings()
