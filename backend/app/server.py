"""HTTP server: streams a panel debate to the browser and serves the studio page.

GET /api/debate?question=...&guests=karusela,agent,fan   live debate (Claude, costs money)
GET /api/debate?demo=1                                    replay a recorded debate (free)

The response is a Server-Sent Events stream. For every turn the browser gets:
  turn_start {speaker, name}          -> the camera cuts to the speaker
  tool       {speaker, name, label}   -> "Miki is checking the league table..."
  speech     {speaker, text, audio, words, wtimes, wdurations}  -> voice + lip-sync
and finally done {cost_usd}. Each finished debate is saved to data/debates/ for replay.

Run (from backend/):  .venv/bin/uvicorn app.server:app --port 8010
"""

import asyncio
import json
import logging
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.agents.panel import GUESTS, PANELISTS, run_panel
from app.agents.pundit import Event
from app.speech.prepare import display_text
from app.speech.tts import synthesize

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEMO_DEBATE = Path(__file__).resolve().parent / "demo" / "sample_debate.json"
SAVED_DEBATES = Path(__file__).resolve().parents[1] / "data" / "debates"
DEMO_TOOL_PAUSE = 0.7  # seconds per tool call in demo mode, so the "thinking" graphic is visible

# What the studio shows while a pundit is looking something up.
TOOL_LABELS = {
    "data_coverage": "בודק אילו נתונים יש",
    "league_table": "בודק את טבלת הליגה",
    "top_scorers": "בודק את טבלת הכובשים",
    "player_stats": "שולף נתוני שחקן",
    "team_form": "בודק את הפורמה של הקבוצה",
    "head_to_head": "בודק מפגשים קודמים",
    "team_match_stats": "מנתח סטטיסטיקות משחק",
    "match_report": "פותח דוח משחק",
    "run_sql": "מריץ שאילתה מיוחדת",
}

app = FastAPI(title="AI Football Studio")
# Avatars are ~9MB each but gzip to ~3.5MB. The SSE stream is excluded by Starlette's defaults,
# so live events are not buffered.
app.add_middleware(GZipMiddleware, minimum_size=1024)


def sse(event: str, data: dict) -> str:
    """One Server-Sent Events message."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def demo_events(path: Path = DEMO_DEBATE) -> Iterator[Event]:
    """Replay a recorded debate as if it were live, without calling Claude."""
    debate = json.loads(path.read_text())
    pause = DEMO_TOOL_PAUSE
    for turn in debate["turns"]:
        speaker = turn["speaker"]
        yield Event("turn_start", {"speaker": speaker, "name": PANELISTS[speaker].name})
        for tool in turn.get("tools", []):
            time.sleep(pause)
            yield Event("tool_call", {"speaker": speaker, "name": tool, "input": {}})
        yield Event("answer", {"speaker": speaker, "text": turn["text"]})
    yield Event("panel_done", {"cost_usd": 0.0})


def debate_stream(question: str, guests: list[str], demo: bool) -> Iterator[str]:
    """Turn panel events into SSE messages, adding a voice to every answer."""
    events = demo_events() if demo else run_panel(question, guests)
    turns = []
    try:
        for event in events:
            speaker = event.data.get("speaker")
            if event.type == "turn_start":
                yield sse("turn_start", {"speaker": speaker, "name": event.data["name"]})
            elif event.type == "tool_call":
                name = event.data["name"]
                yield sse("tool", {"speaker": speaker, "name": name, "label": TOOL_LABELS.get(name, "בודק נתונים")})
            elif event.type == "answer":
                text = event.data["text"]
                speech = asyncio.run(synthesize(text, speaker))  # we run in a worker thread: no loop here
                turns.append({"speaker": speaker, "text": text})
                yield sse("speech", {"speaker": speaker, "text": display_text(text), **speech})
            elif event.type == "error":
                yield sse("error", {"message": event.data["message"]})
                return
            elif event.type == "panel_done":
                if not demo:
                    save_debate(question, guests, turns)
                yield sse("done", {"cost_usd": event.data["cost_usd"]})
    except Exception as e:  # keep the browser informed instead of silently dropping the stream
        log.exception("debate stream failed")
        yield sse("error", {"message": f"שגיאה בשרת: {type(e).__name__}"})


def save_debate(question: str, guests: list[str], turns: list[dict]) -> Path:
    """Keep every live debate so it can be replayed for free (demo mode) or turned into a video."""
    SAVED_DEBATES.mkdir(parents=True, exist_ok=True)
    path = SAVED_DEBATES / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps({"question": question, "guests": guests, "turns": turns},
                               ensure_ascii=False, indent=1))
    return path


@app.get("/api/debate")
def debate(question: str = Query("", max_length=300), guests: str = ",".join(GUESTS), demo: bool = False):
    """Stream a debate as Server-Sent Events (see module docstring)."""
    chosen = [g for g in guests.split(",") if g in GUESTS]
    if not demo and not question.strip():
        return StreamingResponse(iter([sse("error", {"message": "צריך לשאול שאלה"})]),
                                 media_type="text/event-stream")
    # A sync generator: Starlette iterates it in a worker thread, so the blocking Claude calls
    # don't stall the server.
    return StreamingResponse(debate_stream(question, chosen, demo), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# Static files last, so /api/* wins.
# Compressed avatars (1024px WebP textures): see "Compress avatars" in README.
app.mount("/avatars", StaticFiles(directory=ROOT / "frontend" / "avatars"), name="avatars")
app.mount("/", StaticFiles(directory=ROOT / "frontend" / "studio", html=True), name="studio")
