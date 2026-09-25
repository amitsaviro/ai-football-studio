"""Turn a pundit's written answer into text that sounds good when spoken by TTS."""

import re

from app.speech.hebrew_numbers import normalize_for_speech

NIQQUD = re.compile(r"[\u0591-\u05C7]")  # Hebrew vowel points and cantillation marks


def prepare_for_speech(text: str) -> str:
    """Spell out numbers, and shorten the pause after a period.

    Neural voices pause ~0.7s after a period but ~0.2s after a comma; in a fast-moving
    panel the long pauses sound sluggish. '!' and '?' are kept for their intonation.
    """
    text = normalize_for_speech(text)
    return re.sub(r"\.(\s+)(?=\S)", r",\1", text)


def display_text(text: str) -> str:
    """The on-screen version: pundits add niqqud to ambiguous words for the TTS voice only."""
    return NIQQUD.sub("", text)
