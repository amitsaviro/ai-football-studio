"""One pundit answering one question, using the stats tools.

A manual agent loop rather than the SDK's tool runner: the UI will show every step live
("the statistician is checking the league table..."), so the loop yields an event for
each tool call and result instead of only returning the final answer.

    Claude ──tool_use──▶ call_tool() ──tool_result──▶ Claude ── ... ──▶ final text
"""

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field

import anthropic

from app.config import settings
from app.tools.registry import TOOLS, call_tool

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8  # a runaway loop costs money; a good answer needs 1-3 rounds

# USD per million tokens: (input, output). Cache writes cost 1.25x input, cache reads 0.1x.
PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


@dataclass
class Usage:
    """Token counters summed over all API calls of one answer, for cost reporting."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    api_calls: int = 0

    def add(self, u) -> None:
        """Add one response's usage."""
        self.input_tokens += u.input_tokens
        self.output_tokens += u.output_tokens
        self.cache_write_tokens += u.cache_creation_input_tokens or 0
        self.cache_read_tokens += u.cache_read_input_tokens or 0
        self.api_calls += 1

    def cost_usd(self, model: str) -> float | None:
        """Estimated cost in USD from the price table, or None for an unknown model."""
        if model not in PRICES:
            return None
        inp, out = PRICES[model]
        return (self.input_tokens * inp + self.cache_write_tokens * inp * 1.25
                + self.cache_read_tokens * inp * 0.1 + self.output_tokens * out) / 1_000_000


@dataclass
class Event:
    """What the pundit is doing right now. type: tool_call | tool_result | answer | error."""
    type: str
    data: dict = field(default_factory=dict)


def ask(question: str, persona: str, history: list[dict] | None = None,
        client: anthropic.Anthropic | None = None) -> Iterator[Event]:
    """Answer `question` in the voice of `persona`, calling tools as needed.

    Yields Events as it works: tool_call and tool_result for every tool use, then a final
    `answer` (text, updated message history, usage/cost) or an `error`. Pass `history` from a
    previous answer's `messages` to continue the same conversation.
    """
    client = client or anthropic.Anthropic()
    messages = list(history or []) + [{"role": "user", "content": question}]
    usage = Usage()
    model = settings.pundit_model

    for _ in range(MAX_TOOL_ROUNDS + 1):
        response = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=persona,
            tools=TOOLS,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": settings.pundit_effort},
            # The tool definitions + persona are identical on every call: cache them.
            cache_control={"type": "ephemeral"},
            # If a safety classifier declines, re-run on a fallback model instead of failing.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        usage.add(response.usage)

        if response.stop_reason == "refusal":
            yield Event("error", {"message": "The model declined to answer this question."})
            return

        # Keep the full content (thinking + tool_use blocks) in history, not just the text.
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            answer = "".join(b.text for b in response.content if b.type == "text").strip()
            if response.stop_reason == "max_tokens":
                answer += "\n[התשובה נקטעה]"
            yield Event("answer", {
                "text": answer,
                "messages": messages,  # lets the caller continue the conversation
                "usage": {**usage.__dict__, "cost_usd": usage.cost_usd(model), "model": model},
            })
            return

        # Claude may call several tools at once; all results go back in ONE user message.
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            yield Event("tool_call", {"name": block.name, "input": block.input})
            result = call_tool(block.name, block.input)
            yield Event("tool_result", {"name": block.name, "result": result})
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False),
                "is_error": "error" in result,
            })
        messages.append({"role": "user", "content": results})

    yield Event("error", {"message": f"Stopped after {MAX_TOOL_ROUNDS} tool rounds without an answer."})
