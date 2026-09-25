"""The panel: several pundits debating one question, run from a fixed script.

Each turn is an independent `ask()` call. The speaker gets the question plus a transcript
of what was said so far — like a real panelist, they hear the others' words, not their
tool calls. That also keeps each call small and lets the persona + tools stay cached.

    host opens → statistician answers → ex-player reacts → statistician fact-checks
               → ex-player's last word → host sums up
"""

from collections.abc import Iterator
from dataclasses import dataclass

import anthropic

from app.agents.personas import EX_PLAYER, HOST, STATISTICIAN
from app.agents.pundit import Event, ask


@dataclass(frozen=True)
class Panelist:
    """A seat at the table: display name, system prompt, and whether they may use the stats tools."""
    name: str
    persona: str
    uses_tools: bool = True


PANELISTS = {
    "host": Panelist("אבי המגיש", HOST, uses_tools=False),
    "stats": Panelist("הסטטיסטיקאי", STATISTICIAN),
    "karusela": Panelist("יוסי קרוסלה", EX_PLAYER),
}

# (speaker, what this turn is for). The instruction is appended after the transcript.
SCRIPT: list[tuple[str, str]] = [
    ("host", "פתח את הדיון: הצג את השאלה לצופים ב-2–3 משפטים קצרים והעבר את רשות הדיבור "
             "לסטטיסטיקאי. אל תענה על השאלה בעצמך."),
    ("stats", "ענה על השאלה עם נתונים."),
    ("karusela", "הגב לסטטיסטיקאי מהזווית שלך. אם אתה חושב אחרת — תגיד את זה בבירור. "
                 "מותר לך לבדוק נתונים כדי לחזק את הטענה שלך."),
    ("stats", "עשה Fact-check לדברים של יוסי: בדוק עם הכלים כל טענה עובדתית שלו, "
              "ואמור מה נכון, מה לא נכון ומה אי אפשר לבדוק. תהיה הוגן — אם הוא צדק, תגיד."),
    ("karusela", "מילה אחרונה: הגב ל-Fact-check ב-2–4 משפטים."),
    ("host", "סכם את הדיון ב-4–6 משפטים: מה הנתונים הראו, איפה יוסי תרם זווית שהמספרים לא "
             "רואים, איפה הם לא הסכימו — וסיים ב'שורה התחתונה' שלך. רק מספרים שנאמרו בדיון."),
]


def _turn_prompt(question: str, transcript: list[tuple[str, str]], instruction: str) -> str:
    lines = [f"השאלה לפאנל: {question}", ""]
    if transcript:
        lines.append("מה נאמר עד עכשיו בדיון:")
        lines += [f"[{speaker}]: {text}" for speaker, text in transcript]
        lines.append("")
    lines.append(f"התור שלך: {instruction}")
    return "\n".join(lines)


def run_panel(question: str, client: anthropic.Anthropic | None = None) -> Iterator[Event]:
    """Run the whole debate on `question`, yielding events tagged with the speaker.

    Event types: turn_start, tool_call, tool_result, answer, error (from `ask`, each with a
    `speaker` field), and a final panel_done with the transcript and total cost.
    """
    client = client or anthropic.Anthropic()
    transcript: list[tuple[str, str]] = []
    total_cost = 0.0

    for speaker_key, instruction in SCRIPT:
        panelist = PANELISTS[speaker_key]
        yield Event("turn_start", {"speaker": speaker_key, "name": panelist.name})
        prompt = _turn_prompt(question, transcript, instruction)
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
