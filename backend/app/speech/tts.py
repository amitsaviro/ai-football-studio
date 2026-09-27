"""Text-to-speech for the panel: one voice per character, with per-word timings for lip-sync.

There is a single male Hebrew neural voice (Avri), so characters differ by pitch and speed.
Uses edge-tts (Microsoft neural voices, unofficial endpoint): fine for development; production
should switch to the official Azure Speech free tier, which returns the same word boundaries.
"""

import base64
from dataclasses import dataclass

import edge_tts

from app.speech.diacritize import add_niqqud
from app.speech.prepare import prepare_for_speech

TICKS_PER_MS = 10_000  # edge-tts reports offsets in 100-nanosecond units


@dataclass(frozen=True)
class Voice:
    """How one character sounds: TTS voice plus pitch and speaking-rate offsets."""
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


async def synthesize(text: str, speaker: str) -> dict:
    """Speak `text` in the speaker's voice.

    Returns base64 MP3 audio plus TalkingHead-style timings: words, wtimes (ms), wdurations (ms).
    The text is prepared for speech first (numbers as words, shorter pauses) and vocalized.
    """
    voice = VOICES.get(speaker, Voice())
    spoken = add_niqqud(prepare_for_speech(text))
    communicate = edge_tts.Communicate(spoken, voice.name, rate=voice.rate, pitch=voice.pitch,
                                       boundary="WordBoundary")
    audio = bytearray()
    words, wtimes, wdurations = [], [], []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            words.append(chunk["text"])
            wtimes.append(round(chunk["offset"] / TICKS_PER_MS))
            wdurations.append(round(chunk["duration"] / TICKS_PER_MS))
    return {
        "audio": base64.b64encode(bytes(audio)).decode("ascii"),
        "words": words, "wtimes": wtimes, "wdurations": wdurations,
    }
