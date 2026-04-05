"""Enhance button — LLM re-prompting with user instructions.

When a user clicks "Enhance", this module takes the current enrichment
output, combines it with optional user instructions and few-shot examples,
and re-prompts the LLM to produce an improved version.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


async def llm_enhance(
    original_output: str,
    user_instructions: str | None = None,
    few_shot_examples: list[dict[str, Any]] | None = None,
    model: str = "gpt-4.1-mini",
) -> str:
    """Re-prompt LLM to improve an enrichment output.

    This is a standalone LLM call — separate from the workflow pipeline.
    The user clicks 'Enhance', optionally provides instructions,
    and the LLM refines the existing output.

    Returns the enhanced output as a JSON string.
    """
    llm = ChatOpenAI(model=model, temperature=0)

    prompt = f"""You are a Lead Enrichment Quality Expert.

Below is an AI-generated lead enrichment output. Your job is to improve it by:
1. Filling any remaining gaps with reasonable estimates (mark clearly as "[Estimated]")
2. Improving data consistency and accuracy
3. Removing any duplicate or conflicting entries
4. Making the executive summary more actionable for sales teams
5. Ensuring all scores are properly calibrated (0-1 for confidence, 0-100 for others)

## Current Output:
```json
{original_output[:8000]}
```
"""

    if user_instructions:
        prompt += f"""
## User Instructions (PRIORITY — follow these carefully):
{user_instructions}
"""

    if few_shot_examples:
        prompt += "\n## High-Quality Reference Examples:\n"
        for i, ex in enumerate(few_shot_examples[:3]):
            prompt += (
                f"### Example {i + 1} (Rating: {ex['rating']}/5)\n"
                f"**Company:** {ex['company_name']}\n"
                f"```json\n{ex['output_response'][:1500]}\n```\n\n"
            )

    prompt += """
## Enhanced Output:
Return the improved enrichment as a valid JSON object. Maintain the same structure
but with better data quality, filled gaps, and improved insights.
"""

    logger.info("[Enhancer] Starting LLM enhancement call")
    response = await llm.ainvoke(prompt)
    result = response.content

    # Try to extract JSON from the response
    json_match = re.search(r"```(?:json)?\s*\n(.*?)```", result, re.DOTALL)
    if json_match:
        result = json_match.group(1).strip()

    # Validate it's valid JSON
    try:
        json.loads(result)
    except json.JSONDecodeError:
        logger.warning("[Enhancer] LLM output is not valid JSON, returning raw")

    logger.info("[Enhancer] Enhancement completed, output length: %d", len(result))
    return result
