"""Text-to-speech for the panel: one voice per character, with per-word timings for lip-sync.

Speech is made in two steps:
1. edge-tts (Microsoft neural voices, unofficial endpoint) speaks the text with the only male
   Hebrew voice, Avri, and reports when each word starts: the lip-sync timings.
2. The local voice converter (voice/converter_server.py, Seed-VC) re-voices that audio as the
   character's own voice. It keeps the timing, so step 1's word timings stay valid. If the
   converter isn't running, the character just speaks as Avri (with their own pitch and pace).

Results are cached on disk, so replaying a debate costs nothing after the first time.
Production should switch step 1 to the official Azure Speech free tier (same word boundaries).
"""

import base64
import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import edge_tts
import httpx

from app.config import settings
from app.speech.diacritize import add_niqqud
from app.speech.prepare import prepare_for_speech

log = logging.getLogger(__name__)

TICKS_PER_MS = 10_000  # edge-tts reports offsets in 100-nanosecond units
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "tts_cache"
CACHE_VERSION = 1  # bump when the speech pipeline changes, to re-render cached speech
CONVERT_TIMEOUT = 120  # seconds; a long turn takes ~10s on an M-series GPU


@dataclass(frozen=True)
class Voice:
    """How one character sounds before conversion: TTS voice plus pitch and speaking-rate offsets."""
    name: str = "he-IL-AvriNeural"
    rate: str = "+10%"
    pitch: str = "+0Hz"


VOICES = {
    "host": Voice(rate="+14%", pitch="+2Hz"),       # Avi: energetic TV host
    "stats": Voice(rate="+6%", pitch="+4Hz"),       # Miki: measured, a bit higher
    "karusela": Voice(rate="+22%", pitch="-6Hz"),   # Yossi: deep and excited
    "agent": Voice(rate="+12%", pitch="-10Hz"),     # Moti: deep, smooth talker
    "fan": Voice(rate="+26%", pitch="+8Hz"),        # Tzachi: fast and high, from the stands
}


async def speak(text: str, voice: Voice) -> tuple[bytes, dict]:
    """Step 1: TTS audio (MP3) plus TalkingHead-style timings: words, wtimes (ms), wdurations (ms)."""
    communicate = edge_tts.Communicate(text, voice.name, rate=voice.rate, pitch=voice.pitch,
                                       boundary="WordBoundary")
    audio = bytearray()
    timings = {"words": [], "wtimes": [], "wdurations": []}
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            timings["words"].append(chunk["text"])
            timings["wtimes"].append(round(chunk["offset"] / TICKS_PER_MS))
            timings["wdurations"].append(round(chunk["duration"] / TICKS_PER_MS))
    return bytes(audio), timings


async def convert_voice(audio: bytes, speaker: str) -> bytes | None:
    """Step 2: re-voice the audio as `speaker`. None if the converter is off or unreachable."""
    if not settings.voice_converter_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=CONVERT_TIMEOUT) as client:
            response = await client.post(f"{settings.voice_converter_url}/convert",
                                         params={"speaker": speaker}, content=audio)
            response.raise_for_status()
            return response.content
    except httpx.HTTPError as e:
        log.warning("voice converter unavailable (%s); %s speaks in the TTS voice", e, speaker)
        return None


async def synthesize(text: str, speaker: str) -> dict:
    """Speak `text` in the speaker's voice.

    Returns base64 MP3 audio plus TalkingHead-style timings: words, wtimes (ms), wdurations (ms).
    The text is prepared for speech first (numbers as words, shorter pauses) and vocalized.
    """
    voice = VOICES.get(speaker, Voice())
    spoken = add_niqqud(prepare_for_speech(text))
    key = hashlib.sha256(json.dumps([CACHE_VERSION, speaker, asdict(voice), spoken]).encode()).hexdigest()
    cached = CACHE_DIR / f"{key}.json"
    if cached.exists():
        return json.loads(cached.read_text())

    audio, timings = await speak(spoken, voice)
    converted = await convert_voice(audio, speaker)
    result = {"audio": base64.b64encode(converted or audio).decode("ascii"), **timings}
    if converted:  # don't cache the fallback, so the real voice is used once the converter is up
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(result))
    return result
