"""Run a full panel debate from the terminal.

Usage (from backend/):
    python scripts/panel.py "האם דור פרץ הוא השחקן הכי טוב בליגה העונה?"
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.panel import run_panel  # noqa: E402

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"
COLORS = {"host": "\033[33m", "stats": "\033[36m", "karusela": "\033[35m"}  # yellow, cyan, magenta


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit('Usage: python scripts/panel.py "השאלה לפאנל"')
    question = " ".join(sys.argv[1:])

    for event in run_panel(question):
        color = COLORS.get(event.data.get("speaker"), "")
        if event.type == "turn_start":
            print(f"\n{color}{BOLD}▶ {event.data['name']}{RESET}")
        elif event.type == "tool_call":
            args = json.dumps(event.data["input"], ensure_ascii=False)
            print(f"{DIM}  🔧 {event.data['name']}({args}){RESET}")
        elif event.type == "answer":
            print(f"{color}{event.data['text']}{RESET}")
        elif event.type == "error":
            print(f"שגיאה: {event.data['message']}")
        elif event.type == "panel_done":
            print(f"\n{DIM}[סה״כ עלות הדיון: ${event.data['cost_usd']:.3f}]{RESET}")


if __name__ == "__main__":
    main()
