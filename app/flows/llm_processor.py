"""Single LLM call for intelligence tasks ONLY.

Input:  All pre-fetched, validated, normalized data from APIs.
Output: Merged data + lead scores + executive summary + recommendations.

The LLM does:    Fill missing data, remove duplicates, score lead, generate insights.
The LLM does NOT: Select APIs, call APIs, handle retries, control workflow.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from crewai import Agent, Crew, Process, Task
from crewai import LLM

from app.config.settings import settings

logger = logging.getLogger(__name__)


def _build_prompt(
    company_name: str,
    contacts: list[dict[str, Any]],
    news: list[dict[str, Any]],
    financials: dict[str, Any],
    few_shot_examples: list[dict[str, Any]] | None = None,
) -> str:
    """Build the single intelligence prompt with all pre-fetched data."""

    # Few-shot section from feedback loop
    examples_section = ""
    if few_shot_examples:
        examples_section = (
            "\n\n## Reference Examples (high-rated past outputs — match this quality):\n"
        )
        for i, ex in enumerate(few_shot_examples[:3]):
            examples_section += (
                f"### Example {i + 1} (User Rating: {ex['rating']}/5)\n"
                f"**Company:** {ex['company_name']}\n"
                f"**Output:**\n```json\n{ex['output_response'][:2000]}\n```\n\n"
            )

    return f"""You are a Lead Intelligence Analyst.
All data below has already been fetched from external APIs by our system.
You do NOT call any APIs. You do NOT decide which tools to use.

Your ONLY job is to analyze this pre-fetched data and produce a unified output.

## Pre-Fetched Contact Data (from multiple sources):
```json
{json.dumps(contacts, indent=2, default=str)[:8000]}
```

## Pre-Fetched News Data:
```json
{json.dumps(news, indent=2, default=str)[:4000]}
```

## Pre-Fetched Financial Data:
```json
{json.dumps(financials, indent=2, default=str)[:4000]}
```
{examples_section}

## Your Tasks (do ALL in this single response):

1. **FILL MISSING DATA**: If Source A has email but no phone, and Source B has phone
   but no email for the same person — merge them into one complete record.

2. **REMOVE DUPLICATES**: If the same person appears from Lusha and Apollo, keep the
   version with the most complete data. Don't list them twice.

3. **LEAD SCORING**: Compute these scores:
   - confidence_score (0.0-1.0): How reliable is this overall data?
   - firmographic_score (0-100): Company size and fit assessment
   - intent_score (0-100): Buying signals from news
   - growth_score (0-100): Growth trajectory

4. **EXECUTIVE SUMMARY**: Write a 3-5 sentence overview covering {company_name}'s
   market position, recent activity, and key contacts.

5. **RECOMMENDATIONS**: List 3-5 actionable recommendations for the sales team.

Return a single JSON object with this exact structure:
{{
   "merged_contacts": [
       {{
           "full_name": "...",
           "title": "...",
           "email": "...",
           "phone": "...",
           "linkedin_url": "...",
           "company": "...",
           "sources": ["lusha", "apollo"]
       }}
   ],
   "lead_scores": {{
       "confidence_score": 0.85,
       "firmographic_score": 72,
       "intent_score": 65,
       "growth_score": 58
   }},
   "executive_summary": "...",
   "recommendations": ["...", "..."],
   "news_summary": ["..."],
   "financials_summary": {
       "revenue": 0,
       "employee_count": 0
   },
   "dedup_summary": "Merged X duplicates, filled Y missing fields"
}}"""


def run_intelligence(
    company_name: str,
    contacts: list[dict[str, Any]],
    news: list[dict[str, Any]],
    financials: dict[str, Any],
    few_shot_examples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute a SINGLE LLM call: merge + fill gaps + dedup + score + insights.

    Critical constraints:
    - tools=[]        → agent cannot call any external tools
    - max_iter=1      → single iteration, no looping
    - allow_delegation=False → cannot hand off work
    """
    llm = LLM(
        model=settings.llm_model or "gpt-4o-mini",
        temperature=0,
    )

    prompt = _build_prompt(company_name, contacts, news, financials, few_shot_examples)

    agent = Agent(
        role="Lead Intelligence Analyst",
        goal=(
            "Analyze pre-fetched lead data: fill missing fields, remove duplicates, "
            "compute lead scores, and generate an executive summary with recommendations."
        ),
        backstory=(
            "You are a data analyst. All data has been pre-fetched by the system. "
            "You NEVER call APIs. You NEVER decide tool usage. You ONLY analyze "
            "the data given to you and produce structured output."
        ),
        tools=[],               # ← NO TOOLS — critical constraint
        verbose=True,
        allow_delegation=False,
        max_iter=1,             # ← SINGLE iteration, no looping
        llm=llm,
    )

    task = Task(
        description=prompt,
        expected_output=(
            "JSON with merged_contacts, lead_scores, executive_summary, "
            "recommendations, and dedup_summary"
        ),
        agent=agent,
    )

    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )

    logger.info("[LLM Intelligence] Starting single LLM call for '%s'", company_name)
    result = crew.kickoff()
    result_str = str(result)
    logger.info("[LLM Intelligence] Completed for '%s' — output length: %d", company_name, len(result_str))

    try:
        # Try to parse as JSON
        parsed = json.loads(result_str)
        return parsed
    except json.JSONDecodeError:
        # Try to extract JSON from markdown code blocks
        import re
        json_match = re.search(r"```(?:json)?\s*\n(.*?)```", result_str, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        logger.warning("[LLM Intelligence] Could not parse LLM output as JSON")
        return {"raw_output": result_str, "parse_error": True}
