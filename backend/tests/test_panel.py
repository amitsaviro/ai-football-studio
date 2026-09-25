"""Panel orchestration tests. No API calls: they check the script and prompts, not the model."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.panel import GUESTS, PANELISTS, _turn_prompt, build_script, run_panel  # noqa: E402


@pytest.mark.parametrize("guests", [[], ["karusela"], list(GUESTS)])
def test_script_shape(guests):
    speakers = [speaker for speaker, _ in build_script(guests)]
    assert speakers[0] == speakers[-1] == "host"          # host opens and closes
    assert speakers[1] == "stats"                           # facts come first
    assert speakers.count("stats") == 2                     # answer + fact-check
    for g in guests:
        assert speakers.count(g) == 2                       # react + last word
    assert len(speakers) == 4 + 2 * len(guests)


def test_fact_check_comes_after_every_guest_reacted():
    speakers = [speaker for speaker, _ in build_script(list(GUESTS))]
    fact_check = len(speakers) - 1 - speakers[::-1].index("stats")
    assert all(speakers.index(g) < fact_check for g in GUESTS)


def test_only_the_host_talks_without_tools():
    assert [k for k, p in PANELISTS.items() if not p.uses_tools] == ["host"]


def test_turn_prompt_includes_cast_and_transcript():
    prompt = _turn_prompt("שאלה?", ["host", "stats", "fan"], [("הסטטיסטיקאי", "8 שערים")], "הגב")
    assert "צחי מהיציע" in prompt and "[הסטטיסטיקאי]: 8 שערים" in prompt
    assert prompt.rstrip().endswith("התור שלך: הגב")
    assert "מוטי דיל" not in prompt  # guests who aren't at the table aren't mentioned


def test_unknown_guest_is_rejected():
    with pytest.raises(ValueError):
        next(run_panel("שאלה?", ["messi"]))
