"""The panel: several pundits debating one question.

The host and the statistician are always at the table (one runs the show, one checks the
facts); guests are chosen per debate. The script is built from the cast:

    host opens → statistician answers → each guest reacts → statistician fact-checks
               → each guest's last word → host sums up

Each turn is an independent `ask()` call. The speaker gets the question, the cast and a
transcript of what was said so far — like a real panelist, they hear the others' words, not
their tool calls. That keeps each call small and lets the persona + tools stay cached.
"""

from collections.abc import Iterator
from dataclasses import dataclass

import anthropic

from app.agents.personas import EX_PLAYER, HOST, STATISTICIAN, SUPER_AGENT, SUPER_FAN
from app.agents.pundit import Event, ask


@dataclass(frozen=True)
class Panelist:
    """A seat at the table: display name, one-line intro for the others, system prompt, tool access."""
    name: str
    intro: str
    persona: str
    uses_tools: bool = True


PANELISTS = {
    "host": Panelist("אבי המגיש", "מנחה את הדיון", HOST, uses_tools=False),
    "stats": Panelist("מיקי הסטטיסטיקאי", "יבש ומדויק, מביא מספרים ובודק עובדות", STATISTICIAN),
    "karusela": Panelist("יוסי קרוסלה", "כוכב נבחרת לשעבר, מדבר מהלב על רעב ואופי", EX_PLAYER),
    "agent": Panelist("מוטי דיל", "סוכן שחקנים, אצלו הכול ביזנס וערך שוק", SUPER_AGENT),
    "fan": Panelist("צחי מהיציע", "פריק של כדורגל, הקול של היציע, 100% רגש", SUPER_FAN),
}
GUESTS = ("karusela", "agent", "fan")


def build_script(guests: list[str]) -> list[tuple[str, str]]:
    """The turn order for a debate with these guests: (speaker key, instruction for that turn)."""
    script = [
        ("host", "פתח את הדיון: הצג את השאלה ואת המשתתפים ב-2–3 משפטים קצרים, והעבר את רשות "
                 "הדיבור למיקי הסטטיסטיקאי. אל תענה על השאלה בעצמך."),
        ("stats", "ענה על השאלה עם נתונים."),
    ]
    script += [(g, "הגב לדברים שנאמרו עד עכשיו מהזווית שלך, ב-3–5 משפטים. אם אתה לא מסכים עם "
                   "מישהו — פנה אליו בשמו ותגיד את זה בבירור.") for g in guests]
    script.append(("stats", "עשה Fact-check לכל הטענות העובדתיות שנאמרו בדיון: בדוק אותן עם הכלים, "
                            "ואמור מה נכון, מה לא נכון ומה אי אפשר לבדוק (דעות, רגש, חוזים). "
                            "תהיה הוגן — אם מישהו צדק, תגיד."))
    # Last words come after the fact-check, so nobody would verify a new number said there.
    script += [(g, "מילה אחרונה: 2–3 משפטים, בתגובה ל-Fact-check או למי שהכי עצבן אותך. "
                   "בלי מספרים חדשים — אחרי ה-Fact-check אף אחד כבר לא יבדוק אותם.") for g in guests]
    script.append(("host", "סכם את הדיון ב-4–6 משפטים: מה הנתונים הראו, איזו זווית כל משתתף הוסיף, "
                           "איפה הם לא הסכימו — וסיים ב'שורה התחתונה' שלך. צטט רק מספרים שנאמרו "
                           "עד ה-Fact-check של מיקי (כולל), כי רק הם נבדקו."))
    return script


def _turn_prompt(question: str, cast: list[str], transcript: list[tuple[str, str]], instruction: str) -> str:
    lines = [f"השאלה לפאנל: {question}", "", "משתתפי הפאנל:"]
    lines += [f"- {PANELISTS[k].name}: {PANELISTS[k].intro}" for k in cast]
    lines.append("")
    if transcript:
        lines.append("מה נאמר עד עכשיו בדיון:")
        lines += [f"[{speaker}]: {text}" for speaker, text in transcript]
        lines.append("")
    lines.append(f"התור שלך: {instruction}")
    return "\n".join(lines)


def run_panel(question: str, guests: list[str] | None = None,
              client: anthropic.Anthropic | None = None) -> Iterator[Event]:
    """Run the whole debate on `question`, yielding events tagged with the speaker.

    `guests` picks who joins the host and the statistician (default: everyone).
    Event types: turn_start, tool_call, tool_result, answer, error (from `ask`, each with a
    `speaker` field), and a final panel_done with the transcript and total cost.
    """
    guests = list(GUESTS if guests is None else guests)
    unknown = [g for g in guests if g not in GUESTS]
    if unknown:
        raise ValueError(f"Unknown guests {unknown}; choose from {GUESTS}")
    client = client or anthropic.Anthropic()
    cast = ["host", "stats", *guests]
    transcript: list[tuple[str, str]] = []
    total_cost = 0.0

    for speaker_key, instruction in build_script(guests):
        panelist = PANELISTS[speaker_key]
        yield Event("turn_start", {"speaker": speaker_key, "name": panelist.name})
        prompt = _turn_prompt(question, cast, transcript, instruction)
        tools = None if panelist.uses_tools else []

        for event in ask(prompt, panelist.persona, client=client, tools=tools):
            event.data["speaker"] = speaker_key
            if event.type == "answer":
                transcript.append((panelist.name, event.data["text"]))
                total_cost += event.data["usage"]["cost_usd"] or 0.0
                event.data.pop("messages", None)  # per-turn history isn't needed by panel callers
            yield event
            if event.type == "error":
                return  # a broken turn would derail the rest of the debate

    yield Event("panel_done", {"transcript": transcript, "cost_usd": total_cost})
