"""Rewrite digits in Hebrew text as spoken words, before sending it to text-to-speech.

TTS voices stumble on things like "2025/26" or "ב-29". Spelling them out the way people
actually say them makes the speech clear and gives the lip-sync real words to work with.

Uses the colloquial (feminine) counting forms — "תשע עשרה שערים" is how most Israelis say it.
"""

import re

UNITS = ["אפס", "אחת", "שתיים", "שלוש", "ארבע", "חמש", "שש", "שבע", "שמונה", "תשע"]
TEENS = ["עשר", "אחת עשרה", "שתים עשרה", "שלוש עשרה", "ארבע עשרה", "חמש עשרה",
         "שש עשרה", "שבע עשרה", "שמונה עשרה", "תשע עשרה"]
TENS = ["", "", "עשרים", "שלושים", "ארבעים", "חמישים", "שישים", "שבעים", "שמונים", "תשעים"]
HUNDREDS = ["", "מאה", "מאתיים", "שלוש מאות", "ארבע מאות", "חמש מאות", "שש מאות",
            "שבע מאות", "שמונה מאות", "תשע מאות"]
THOUSANDS = {1: "אלף", 2: "אלפיים", 3: "שלושת אלפים", 4: "ארבעת אלפים", 5: "חמשת אלפים",
             6: "ששת אלפים", 7: "שבעת אלפים", 8: "שמונת אלפים", 9: "תשעת אלפים"}


def _parts(n: int) -> list[str]:
    """0 < n < 1,000,000 as a list of word groups, without the joining ו."""
    parts = []
    thousands, n = divmod(n, 1000)
    if thousands:
        parts.append(THOUSANDS.get(thousands) or f"{number_to_words(thousands)} אלף")
    hundreds, n = divmod(n, 100)
    if hundreds:
        parts.append(HUNDREDS[hundreds])
    if 10 <= n < 20:
        parts.append(TEENS[n - 10])
    else:
        tens, units = divmod(n, 10)
        if tens:
            parts.append(TENS[tens])
        if units:
            parts.append(UNITS[units])
    return parts


def number_to_words(n: int) -> str:
    """12 -> 'שתים עשרה', 29 -> 'עשרים ותשע', 2025 -> 'אלפיים עשרים וחמש'."""
    if n == 0:
        return UNITS[0]
    if n >= 1_000_000:
        return " ".join(UNITS[int(d)] for d in str(n))  # rare in football talk: read digit by digit
    parts = _parts(n)
    if len(parts) > 1:
        parts[-1] = "ו" + parts[-1]  # Hebrew puts ו before the last group: "עשרים ותשע"
    return " ".join(parts)


def _decimal(match: re.Match) -> str:
    whole, frac = match.group(1), match.group(2)
    return f"{number_to_words(int(whole))} נקודה {' '.join(UNITS[int(d)] for d in frac)}"


def normalize_for_speech(text: str) -> str:
    """Spell out numbers in Hebrew text so TTS reads them naturally."""
    # Seasons: 2025/26 -> "עשרים וחמש עשרים ושש"
    text = re.sub(r"\b(\d{2})(\d{2})/(\d{2})\b",
                  lambda m: f"{number_to_words(int(m.group(2)))} {number_to_words(int(m.group(3)))}", text)
    # Hebrew prefix letter + hyphen + number: "ב-29" -> "בעשרים ותשע"
    text = re.sub(r"([בהוכלמש])[-־](\d+(?:\.\d+)?)",
                  lambda m: m.group(1) + normalize_for_speech(m.group(2)), text)
    # Percent
    text = re.sub(r"(\d+(?:\.\d+)?)\s*%", lambda m: f"{m.group(1)} אחוז", text)
    # Decimals, then whole numbers
    text = re.sub(r"(\d+)\.(\d+)", _decimal, text)
    text = re.sub(r"\d+", lambda m: number_to_words(int(m.group())), text)
    return text
