"""Speech pipeline: TTS -> voice conversion -> cache. Network calls are faked."""

import asyncio
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.speech import tts  # noqa: E402

TIMINGS = {"words": ["שלום"], "wtimes": [50], "wdurations": [400]}


@pytest.fixture
def calls(monkeypatch, tmp_path):
    """Fake TTS and converter; record how often each is called."""
    calls = {"speak": 0, "convert": 0, "converter_up": True}

    async def fake_speak(text, voice):
        calls["speak"] += 1
        return b"avri", TIMINGS

    async def fake_convert(audio, speaker):
        calls["convert"] += 1
        return f"{speaker}:{audio.decode()}".encode() if calls["converter_up"] else None

    monkeypatch.setattr(tts, "speak", fake_speak)
    monkeypatch.setattr(tts, "convert_voice", fake_convert)
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path)
    return calls


def audio_of(result):
    return base64.b64decode(result["audio"])


def test_character_voice_keeps_tts_timings(calls):
    result = asyncio.run(tts.synthesize("שלום", "stats"))
    assert audio_of(result) == b"stats:avri"
    assert {k: result[k] for k in TIMINGS} == TIMINGS   # conversion keeps timing, so lip-sync holds


def test_converted_speech_is_cached(calls):
    first = asyncio.run(tts.synthesize("שלום", "stats"))
    again = asyncio.run(tts.synthesize("שלום", "stats"))
    assert again == first and calls["speak"] == 1


def test_falls_back_to_tts_voice_without_caching(calls):
    calls["converter_up"] = False
    assert audio_of(asyncio.run(tts.synthesize("שלום", "fan"))) == b"avri"
    calls["converter_up"] = True
    assert audio_of(asyncio.run(tts.synthesize("שלום", "fan"))) == b"fan:avri"   # not stuck on Avri
