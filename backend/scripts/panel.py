"""Run a full panel debate from the terminal.

Usage (from backend/):
    python scripts/panel.py "האם דור פרץ הוא השחקן הכי טוב בליגה העונה?"
    python scripts/panel.py --guests agent,fan "השאלה"   # host + statistician + chosen guests
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.speech.prepare import display_text  # noqa: E402

from app.agents.panel import GUESTS, run_panel  # noqa: E402

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"
COLORS = {"host": "\033[33m", "stats": "\033[36m", "karusela": "\033[35m",  # yellow, cyan, magenta
          "agent": "\033[32m", "fan": "\033[31m"}                            # green, red


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--guests", default=",".join(GUESTS),
                        help=f"comma-separated, from: {', '.join(GUESTS)} (default: all)")
    parser.add_argument("question", nargs="+")
    args = parser.parse_args()
    guests = [g.strip() for g in args.guests.split(",") if g.strip()]

    for event in run_panel(" ".join(args.question), guests):
        color = COLORS.get(event.data.get("speaker"), "")
        if event.type == "turn_start":
            print(f"\n{color}{BOLD}▶ {event.data['name']}{RESET}")
        elif event.type == "tool_call":
            call_args = json.dumps(event.data["input"], ensure_ascii=False)
            print(f"{DIM}  🔧 {event.data['name']}({call_args}){RESET}")
        elif event.type == "answer":
            print(f"{color}{display_text(event.data['text'])}{RESET}")
        elif event.type == "error":
            print(f"שגיאה: {event.data['message']}")
        elif event.type == "panel_done":
            print(f"\n{DIM}[סה״כ עלות הדיון: ${event.data['cost_usd']:.3f}]{RESET}")


if __name__ == "__main__":
    main()
