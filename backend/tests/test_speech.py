"""Hebrew number normalization for TTS. Pure functions, no network or DB."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.speech.hebrew_numbers import normalize_for_speech, number_to_words  # noqa: E402
from app.speech.prepare import display_text, prepare_for_speech  # noqa: E402


@pytest.mark.parametrize("n, words", [
    (0, "אפס"), (5, "חמש"), (10, "עשר"), (12, "שתים עשרה"), (19, "תשע עשרה"),
    (20, "עשרים"), (29, "עשרים ותשע"), (100, "מאה"), (129, "מאה עשרים ותשע"),
    (200, "מאתיים"), (1000, "אלף"), (2025, "אלפיים עשרים וחמש"), (15000, "חמש עשרה אלף"),
])
def test_number_to_words(n, words):
    assert number_to_words(n) == words


@pytest.mark.parametrize("text, spoken", [
    ("בעונת 2025/26", "בעונת עשרים וחמש עשרים ושש"),
    ("כבש 19 שערים ב-29 פתיחות", "כבש תשע עשרה שערים בעשרים ותשע פתיחות"),
    ("0.66 למשחק", "אפס נקודה שש שש למשחק"),
    ("61.8% החזקת כדור", "שישים ואחת נקודה שמונה אחוז החזקת כדור"),
    ("ו-3 בישולים", "ושלוש בישולים"),
    ("בלי מספרים בכלל", "בלי מספרים בכלל"),
])
def test_normalize_for_speech(text, spoken):
    assert normalize_for_speech(text) == spoken


def test_prepare_for_speech_shortens_period_pauses_only():
    spoken = prepare_for_speech("כבש 8. זה הרעב! אתה בטוח? כן.")
    assert spoken == "כבש שמונה, זה הרעב! אתה בטוח? כן."


def test_niqqud_is_kept_for_speech_and_removed_for_display():
    text = "זה הָרָעָב! 3 שערים."
    assert "הָרָעָב" in prepare_for_speech(text)
    assert display_text(text) == "זה הרעב! 3 שערים."
