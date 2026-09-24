"""Ask the statistician a question from the terminal and watch every step.

Usage (from backend/):
    python scripts/ask.py "מי מוביל בטבלת הכובשים העונה?"
    python scripts/ask.py            # interactive: keeps the conversation going
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.personas import STATISTICIAN  # noqa: E402
from app.agents.pundit import ask  # noqa: E402

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"


def run(question: str, history: list[dict]) -> list[dict]:
    for event in ask(question, STATISTICIAN, history):
        if event.type == "tool_call":
            args = json.dumps(event.data["input"], ensure_ascii=False)
            print(f"{DIM}🔧 {event.data['name']}({args}){RESET}")
        elif event.type == "tool_result":
            preview = json.dumps(event.data["result"], ensure_ascii=False)
            print(f"{DIM}   ↳ {preview[:160]}{'…' if len(preview) > 160 else ''}{RESET}")
        elif event.type == "answer":
            u = event.data["usage"]
            print(f"\n{BOLD}הסטטיסטיקאי:{RESET} {event.data['text']}\n")
            cost = f"${u['cost_usd']:.4f}" if u["cost_usd"] is not None else "?"
            print(f"{DIM}[{u['model']} | {u['api_calls']} calls | in {u['input_tokens']} "
                  f"+ cache r/w {u['cache_read_tokens']}/{u['cache_write_tokens']} | out {u['output_tokens']} "
                  f"| ≈{cost}]{RESET}")
            return event.data["messages"]
        elif event.type == "error":
            print(f"שגיאה: {event.data['message']}")
    return history


def main() -> None:
    if len(sys.argv) > 1:
        run(" ".join(sys.argv[1:]), [])
        return
    history: list[dict] = []
    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if question:
            history = run(question, history)


if __name__ == "__main__":
    main()
