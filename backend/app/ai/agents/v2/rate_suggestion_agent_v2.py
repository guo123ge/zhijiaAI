"""RateSuggestionAgentV2 — HKSMM4 rate suggestion with tool-calling.

Upgrades the original rate_suggestion_agent to a tool-calling agent
that can search historical items, analyze prices, and suggest rates.
"""

from __future__ import annotations

import json

from app.ai.framework.base_agent import BaseAgent
from app.ai.framework.context import AgentContext
from app.ai.framework.types import AgentResult


class RateSuggestionAgentV2(BaseAgent):
    """HKSMM4 rate suggestion agent — suggests unit rates for BOQ items."""

    @property
    def name(self) -> str:
        return "rate_suggestion_agent"

    @property
    def description(self) -> str:
        return "费率建议 Agent：为HKSMM4清单项建议合理的单价范围和推荐费率"

    @property
    def tool_names(self) -> list[str]:
        return [
            "find_similar_historical_items",
            "query_boq_items",
            "get_cost_breakdown",
            "get_material_prices",
        ]

    @property
    def max_turns(self) -> int:
        return 15

    @property
    def system_prompt(self) -> str:
        return """\
You are an expert Hong Kong quantity surveyor specializing in HKSMM4 rate estimation.

## Your Task
Suggest a reasonable unit rate for a given BOQ item based on:
1. Trade section typical ranges
2. Historical rates from similar items in the project
3. Current market conditions and material prices

## Tools Available
- find_similar_historical_items: Find similar items for rate comparison
- query_boq_items: Check other items in the same trade section
- get_cost_breakdown: Understand project cost structure
- get_material_prices: Get current material/labor/machine rates

## Output Format (JSON)
{
    "suggested_rate": <number>,
    "rate_low": <number>,
    "rate_high": <number>,
    "currency": "HKD",
    "reasoning": "<brief explanation>",
    "confidence": <0.0-1.0>
}

## Principles
- Always provide a range, not just a single number
- State your confidence level honestly
- Reference specific data sources for your estimate
- Consider unit compatibility when comparing rates
"""

    def build_user_message(self, ctx: AgentContext, instruction: str) -> str:
        boq = ctx.get_boq_item()
        if not boq:
            return instruction or "Please suggest a rate for the given BOQ item."

        boq_info = {
            "boq_item_id": boq.id,
            "code": boq.code,
            "name": boq.name,
            "unit": boq.unit,
            "quantity": boq.quantity,
            "trade_section": getattr(boq, "trade_section", ""),
            "description_en": getattr(boq, "description_en", ""),
        }
        msg = f"Please suggest a unit rate for this HKSMM4 BOQ item:\n{json.dumps(boq_info, ensure_ascii=False, indent=2)}"
        if instruction:
            msg += f"\n\nAdditional context: {instruction}"
        return msg
