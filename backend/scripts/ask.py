"""Ask a pundit a question from the terminal and watch every step.

Usage (from backend/):
    python scripts/ask.py "מי מוביל בטבלת הכובשים העונה?"
    python scripts/ask.py            # interactive: keeps the conversation going
    python scripts/ask.py --pundit karusela "מי השחקן הכי רעב בליגה?"
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.speech.prepare import display_text  # noqa: E402

from app.agents.personas import EX_PLAYER, STATISTICIAN, SUPER_AGENT, SUPER_FAN  # noqa: E402
from app.agents.pundit import ask  # noqa: E402

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"

PUNDITS = {
    "stats": ("מיקי הסטטיסטיקאי", STATISTICIAN),
    "karusela": ("יוסי קרוסלה", EX_PLAYER),
    "agent": ("מוטי דיל", SUPER_AGENT),
    "fan": ("צחי מהיציע", SUPER_FAN),
}


def run(question: str, history: list[dict], pundit: str) -> list[dict]:
    display_name, persona = PUNDITS[pundit]
    for event in ask(question, persona, history):
        if event.type == "tool_call":
            args = json.dumps(event.data["input"], ensure_ascii=False)
            print(f"{DIM}🔧 {event.data['name']}({args}){RESET}")
        elif event.type == "tool_result":
            preview = json.dumps(event.data["result"], ensure_ascii=False)
            print(f"{DIM}   ↳ {preview[:160]}{'…' if len(preview) > 160 else ''}{RESET}")
        elif event.type == "answer":
            u = event.data["usage"]
            print(f"\n{BOLD}{display_name}:{RESET} {display_text(event.data['text'])}\n")
            cost = f"${u['cost_usd']:.4f}" if u["cost_usd"] is not None else "?"
            print(f"{DIM}[{u['model']} | {u['api_calls']} calls | in {u['input_tokens']} "
                  f"+ cache r/w {u['cache_read_tokens']}/{u['cache_write_tokens']} | out {u['output_tokens']} "
                  f"| ≈{cost}]{RESET}")
            return event.data["messages"]
        elif event.type == "error":
            print(f"שגיאה: {event.data['message']}")
    return history


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pundit", choices=PUNDITS, default="stats")
    parser.add_argument("question", nargs="*")
    args = parser.parse_args()
    if args.question:
        run(" ".join(args.question), [], args.pundit)
        return
    history: list[dict] = []
    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if question:
            history = run(question, history, args.pundit)


if __name__ == "__main__":
    main()
