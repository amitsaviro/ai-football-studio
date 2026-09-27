"""Automatic niqqud for the TTS voice, so ambiguous words are read correctly.

Unvocalized Hebrew is ambiguous ("ספר" = sefer / safar / sapar), and the TTS voice guesses.
Phonikud (https://github.com/thewh1teagle/phonikud, CC BY 4.0) vocalizes whole sentences from
context. Niqqud is for the voice only: captions go through display_text(), which strips it.

The ~300MB model is downloaded once (see README); without it, text passes through unchanged.
"""

import logging
import re
import threading
from functools import cache
from pathlib import Path

from app.speech.prepare import NIQQUD

log = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "phonikud-1.0.int8.onnx"

# Phonikud extras the TTS voice doesn't need: '|' after prefixes (ו|מתן), stress (U+05AB)
# and meteg (U+05BD).
EXTRA_MARKS = re.compile(r"[|\u05AB\u05BD]")
QAMATS_QATAN, QAMATS = "\u05C7", "\u05B8"   # כׇּל: rare code point, the voice may not know it
KUBUTZ_BEFORE_VAV = re.compile(r"\u05BB(?=ו)")  # נְקֻודָּה: kubutz and vav both mark "u"
# Dagesh in ג/ד/ת changes nothing in modern Hebrew, but before וֹ it makes the voice read the vav
# as a consonant: דּוֹר -> "dvor", גּוֹל -> "gvol". (בּ/כּ/פּ are read correctly and must keep it.)
DAGESH_IN_GDT = re.compile(r"([גדת][\u0591-\u05C7]*?)\u05BC")

_lock = threading.Lock()  # debates are voiced in worker threads; load the model once


@cache
def _model():
    """The Phonikud model, or None if it isn't downloaded."""
    if not MODEL_PATH.exists():
        log.warning("Phonikud model not found at %s; speaking without automatic niqqud", MODEL_PATH)
        return None
    from phonikud_onnx import Phonikud  # heavy import, only when actually used
    return Phonikud(str(MODEL_PATH))


def clean(vocalized: str) -> str:
    """Keep only standard niqqud that the TTS voice reads well."""
    vocalized = EXTRA_MARKS.sub("", vocalized).replace(QAMATS_QATAN, QAMATS)
    vocalized = KUBUTZ_BEFORE_VAV.sub("", vocalized)
    return DAGESH_IN_GDT.sub(r"\1", vocalized)


def add_niqqud(text: str) -> str:
    """Vocalize `text` for the voice. Existing niqqud is replaced: the model reads the context."""
    with _lock:
        model = _model()
    if model is None:
        return text
    return clean(model.add_diacritics(NIQQUD.sub("", text)))
