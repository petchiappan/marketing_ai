"""Fallback enrichment agent – fills gaps in lead data using web/news lookup."""

from __future__ import annotations

import json
from typing import Any

from crewai import Agent, Crew, Task

from app.config.settings import settings


def create_fallback_agent(tools: list | None = None, llm: str | None = None) -> Agent:
    """Build the Fallback Enrichment Agent."""
    return Agent(
        role="Fallback Enrichment Agent",
        goal="Search the web extensively to locate specific missing fields for a sales lead.",
        backstory=(
            "You are an investigative search agent handling data recovery for a larger pipeline. "
            "Your objective is to locate very specific missing fields logically."
            "\n\nRULES FOR EXECUTION:\n"
            "- Conduct thorough searches using your tools and analyze the results.\n"
            "- Output a highly detailed, raw Markdown report of what the tools retrieved across the web.\n"
            "- Do not format as JSON. Provide a clear summary of your findings and your reasoning.\n"
            "- Prefer financial or official company domains over third-party aggregators.\n"
            "- Be explicit if a requested field could not be found anywhere.\n"
        ),
        tools=tools or [],
        verbose=True,
        allow_delegation=False,
        max_iter=3,
        llm=llm or settings.llm_identifier,
    )


def extract_strict_json(raw_text: str) -> dict[str, Any]:
    """Micro-LLM call to strictly extract JSON into the Pydantic schema."""
    from langchain_openai import ChatOpenAI
    from app.schemas.fallback_model import FallbackRecoveryData
    from pydantic import ValidationError
    import logging

    llm = ChatOpenAI(
        model=settings.llm_model or "gpt-4o-mini",
        temperature=0,
    )
    
    # We use LangChain's with_structured_output for guaranteed type-casting
    extractor = llm.with_structured_output(FallbackRecoveryData)
    
    try:
        parsed_model = extractor.invoke(
            f"Extract the missing lead variables accurately from the following Markdown report:\n\n{raw_text}"
        )
        # Filter None values out so we only merge successfully found keys
        return {k: v for k, v in parsed_model.model_dump().items() if v is not None}
    except Exception as e:
        # If extraction fails entirely, log and drop to avoid polluting Salesforce
        logging.getLogger(__name__).warning("Fallback Extraction Error: %s", e)
        return {}


def run_fallback(company_name: str, partial_data: dict[str, Any], target_gap: list[str], tools: list) -> dict[str, Any]:
    """Execute the fallback agent to strictly fill target gaps."""
    agent = create_fallback_agent(tools=tools)

    prompt = f"""
### INSTRUCTIONS:
1. You have received the `Partial_Lead_Data` and `Target_Gap` (the specific fields missing).
2. DO NOT overwrite existing valid data.
3. Use available web/news search tools to find ONLY the fields in `Target_Gap` for {company_name}.
4. Provide a rich markdown summary detailing what you searched for, what you found, and where you found it.

INPUT:
{{
  "lead_id": "{company_name}",
  "Partial_Lead_Data": {json.dumps(partial_data, indent=2)},
  "Target_Gap": {json.dumps(target_gap)}
}}
"""

    task = Task(
        description=prompt,
        expected_output="A rich Markdown report detailing your findings and source URLs.",
        agent=agent,
    )

    crew = Crew(
        agents=[agent],
        tasks=[task],
        verbose=True,
    )

    # 1. Agent Generates Raw Analysis
    result = crew.kickoff()
    raw_markdown = str(result)
    
    # 2. Extractor LLM Casts to Strict Pydantic Dictionary
    recovered_dict = extract_strict_json(raw_markdown)

    return {
        "raw_markdown": raw_markdown,
        "recovered_data": recovered_dict,
        "_fallback_prompt": prompt,
        "_fallback_raw_output": raw_markdown,
    }


def run_llm_only_fallback(company_name: str, partial_data: dict[str, Any], target_gap: list[str]) -> dict[str, Any]:
    """Pure LLM fallback — no tools attached, uses LLM knowledge to fill gaps.

    This is invoked when no external search tools are enabled in the system.
    The LLM uses its training knowledge to provide best-effort data.
    """
    import logging
    from langchain_openai import ChatOpenAI
    from app.schemas.fallback_model import FallbackRecoveryData

    logger = logging.getLogger(__name__)
    logger.info("[LLM-Only Fallback] No tools available. Using pure LLM for '%s'. Gaps: %s", company_name, target_gap)

    llm = ChatOpenAI(
        model=settings.llm_model or "gpt-4o-mini",
        temperature=0,
    )

    prompt = f"""You are a Lead Intelligence Analyst. No external search tools are available.
Use your training knowledge to provide the best possible data for the missing fields.

Company: {company_name}

Partial data already collected:
```json
{json.dumps(partial_data, indent=2, default=str)[:6000]}
```

Missing fields (Target_Gap): {json.dumps(target_gap)}

## INSTRUCTIONS:
1. Fill ONLY the fields listed in Target_Gap.
2. Use your knowledge to provide factual, accurate information.
3. If you are NOT confident about a field, leave it as null — do NOT fabricate data.
4. Prefer well-known public information (e.g. CEO names of large companies, known revenue ranges).

Provide your best assessment as a detailed markdown report, then I will extract the structured data.
"""

    try:
        # Step 1: Generate raw analysis via LLM
        raw_response = llm.invoke(prompt)
        raw_markdown = raw_response.content if hasattr(raw_response, 'content') else str(raw_response)
        logger.info("[LLM-Only Fallback] LLM response length: %d", len(raw_markdown))

        # Step 2: Extract structured data using the same extractor
        recovered_dict = extract_strict_json(raw_markdown)
        logger.info("[LLM-Only Fallback] Recovered %d fields: %s", len(recovered_dict), list(recovered_dict.keys()))

        return {
            "raw_markdown": raw_markdown,
            "recovered_data": recovered_dict,
            "_fallback_prompt": prompt,
            "_fallback_raw_output": raw_markdown,
        }
    except Exception as e:
        logger.error("[LLM-Only Fallback] Failed: %s", e)
        return {
            "raw_markdown": "",
            "recovered_data": {},
            "_fallback_prompt": prompt,
            "_fallback_raw_output": f"ERROR: {e}",
        }
