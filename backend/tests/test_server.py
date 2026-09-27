"""Server tests. TTS and the panel are faked: no network, no Claude calls, no cost."""

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import server  # noqa: E402
from app.agents.pundit import Event  # noqa: E402


async def fake_synthesize(text, speaker):
    return {"audio": "QUJD", "words": text.split()[:3], "wtimes": [0, 300, 600], "wdurations": [250, 250, 250]}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "synthesize", fake_synthesize)
    monkeypatch.setattr(server, "DEMO_TOOL_PAUSE", 0)
    monkeypatch.setattr(server, "SAVED_DEBATES", tmp_path / "debates")
    return TestClient(server.app)


def read_events(response):
    events = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_demo_debate_streams_every_turn_with_a_voice(client):
    events = read_events(client.get("/api/debate", params={"demo": 1}))
    names = [e for e, _ in events]
    demo = json.loads(server.DEMO_DEBATE.read_text())
    turns = demo["turns"]
    assert events[0] == ("debate_start", {"question": demo["question"]})
    assert names[1] == "turn_start" and events[1][1]["speaker"] == "host"
    assert names.count("speech") == len(turns)
    assert names[-1] == "done"
    speech = next(d for e, d in events if e == "speech")
    assert {"speaker", "text", "audio", "words", "wtimes", "wdurations"} <= speech.keys()


def test_tool_calls_get_a_hebrew_label(client):
    events = read_events(client.get("/api/debate", params={"demo": 1}))
    labels = [d["label"] for e, d in events if e == "tool"]
    assert "בודק את טבלת הכובשים" in labels


def test_live_debate_without_question_is_rejected(client):
    events = read_events(client.get("/api/debate"))
    assert events == [("error", {"message": "צריך לשאול שאלה"})]


def test_live_debate_is_saved_and_niqqud_hidden_on_screen(client, monkeypatch):
    def fake_panel(question, guests):
        yield Event("turn_start", {"speaker": "host", "name": "אבי המגיש"})
        yield Event("tool_call", {"speaker": "host", "name": "league_table", "input": {}})
        yield Event("answer", {"speaker": "host", "text": "זה הָרָעָב!", "usage": {}})
        yield Event("panel_done", {"transcript": [], "cost_usd": 0.12})
    monkeypatch.setattr(server, "run_panel", fake_panel)
    events = read_events(client.get("/api/debate", params={"question": "שאלה?", "guests": "fan,messi"}))
    assert [e for e, _ in events] == ["debate_start", "turn_start", "tool", "speech", "done"]
    assert events[3][1]["text"] == "זה הרעב!"          # display text: no niqqud
    saved = list((server.SAVED_DEBATES).glob("*.json"))
    assert len(saved) == 1
    record = json.loads(saved[0].read_text())
    assert record["guests"] == ["fan"]                  # unknown guests are dropped
    assert record["turns"][0]["text"] == "זה הָרָעָב!"  # the saved copy keeps niqqud for replay
    assert record["turns"][0]["tools"] == ["league_table"]

    # ...and can be replayed for free, with the same question and thinking bubbles
    replay = read_events(client.get("/api/debate", params={"replay": saved[0].stem}))
    assert replay[0] == ("debate_start", {"question": "שאלה?"})
    assert [e for e, _ in replay] == ["debate_start", "turn_start", "tool", "speech", "done"]


@pytest.mark.parametrize("replay", ["../../.env", "20260101-000000", "latest"])
def test_replay_accepts_only_existing_debate_ids(client, replay):
    events = read_events(client.get("/api/debate", params={"replay": replay}))
    assert events == [("error", {"message": "הדיון לא נמצא"})]


def test_errors_reach_the_browser(client, monkeypatch):
    def broken_panel(question, guests):
        yield Event("turn_start", {"speaker": "host", "name": "אבי המגיש"})
        raise RuntimeError("boom")
    monkeypatch.setattr(server, "run_panel", broken_panel)
    events = read_events(client.get("/api/debate", params={"question": "שאלה?"}))
    assert events[-1][0] == "error"
