"""Generate a Hebrew speech clip plus per-word timings, for avatar lip-sync experiments.

Writes <out>.mp3 and <out>.json ({"words": [...], "wtimes": [ms], "wdurations": [ms]}),
the format TalkingHead's speakAudio() expects for text-driven lip-sync.

Usage (from backend/):
    python scripts/tts_clip.py ../frontend/prototype/yossi "תקשיבו לי..." --pitch=-8Hz --rate=+12%

Uses edge-tts (Microsoft neural voices, unofficial endpoint) — fine for experiments;
production should use the official Azure Speech free tier.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import edge_tts

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.speech.prepare import prepare_for_speech  # noqa: E402

TICKS_PER_MS = 10_000  # edge-tts reports offsets in 100-nanosecond units


async def synthesize(text: str, out: Path, voice: str, rate: str, pitch: str) -> dict:
    spoken = prepare_for_speech(text)  # numbers as words ("ב-29" -> "בעשרים ותשע"), shorter pauses
    communicate = edge_tts.Communicate(spoken, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    audio = bytearray()
    words, wtimes, wdurations = [], [], []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            words.append(chunk["text"])
            wtimes.append(round(chunk["offset"] / TICKS_PER_MS))
            wdurations.append(round(chunk["duration"] / TICKS_PER_MS))
    out.with_suffix(".mp3").write_bytes(audio)
    timing = {"text": text, "spoken": spoken, "voice": voice, "words": words, "wtimes": wtimes, "wdurations": wdurations}
    out.with_suffix(".json").write_text(json.dumps(timing, ensure_ascii=False, indent=1))
    return timing


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", help="output path without extension")
    parser.add_argument("text")
    parser.add_argument("--voice", default="he-IL-AvriNeural")
    parser.add_argument("--rate", default="+0%")
    parser.add_argument("--pitch", default="+0Hz")
    args = parser.parse_args()
    timing = asyncio.run(synthesize(args.text, Path(args.out), args.voice, args.rate, args.pitch))
    print(f"{len(timing['words'])} words, {timing['wtimes'][-1] + timing['wdurations'][-1]} ms")
    for w, t, d in list(zip(timing["words"], timing["wtimes"], timing["wdurations"]))[:6]:
        print(f"  {t:>6} ms  +{d:>4}  {w}")


if __name__ == "__main__":
    main()
