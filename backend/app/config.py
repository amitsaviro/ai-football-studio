import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "postgresql:///football")
    goal_api_key: str = os.getenv("GOAL_API_KEY", "")
    api_football_key: str = os.getenv("API_FOOTBALL_KEY", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Goal API id of Ligat Ha'al
    goal_league_id: str = "cmr77dwbc00i0rx06adepi1hb"


settings = Settings()
