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
        "recovered_data": recovered_dict
    }
