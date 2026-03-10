"""CrewAI orchestrator – coordinates enrichment agents with tool-specific access."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from crewai import Crew, Process, Task
from langchain_openai import ChatOpenAI

from app.schemas.contact_agent import ContactAgentOutput
from app.schemas.financial_agent import FinancialAgentOutput
from app.schemas.news_agent import NewsAgentOutput

from app.agents.contact_agent import create_contact_agent
from app.agents.news_agent import create_news_agent
from app.agents.financial_agent import create_financial_agent
from app.agents.aggregation_agent import create_aggregation_agent
from app.config.settings import settings
from app.infrastructure.prompt_generator import prompt_generator
from app.tools.registry import resolve_tools


# Registry: maps agent_name → agent creator + task builder
AGENT_REGISTRY = {
    "contact_agent": {
        "create": create_contact_agent,
        "build_prompt": lambda pg, company, ctx: pg.build_contact_prompt(company, ctx),
        "expected_output": "JSON object matching ContactAgentOutput schema with request_id, lead_id, agent_name, status, execution_time_ms, data (contacts_found, total_contacts_found, decision_makers_identified), errors, confidence_score, and source_metadata",
        "output_json": ContactAgentOutput,
    },
    "news_agent": {
        "create": create_news_agent,
        "build_prompt": lambda pg, company, ctx: pg.build_news_prompt(company, ctx),
        "expected_output": "JSON object matching NewsAgentOutput schema with request_id, lead_id, agent_name, status, execution_time_ms, data (recent_news, signals_detected, intent_score, overall_sentiment_score), errors, confidence_score, and source_metadata",
        "output_json": NewsAgentOutput,
    },
    "financial_agent": {
        "create": create_financial_agent,
        "build_prompt": lambda pg, company, ctx: pg.build_financial_prompt(company, ctx),
        "expected_output": "JSON object matching FinancialAgentOutput schema with request_id, lead_id, agent_name, status, execution_time_ms, data (company_profile, firmographic_score, growth_score, industry_match_score), errors, confidence_score, and source_metadata",
        "output_json": FinancialAgentOutput,
    },
}


def build_enrichment_crew(
    company_name: str,
    context: dict | None = None,
    tool_assignments: dict[str, list[str]] | None = None,
) -> Crew:
    """
    Build a CrewAI Crew for enriching a single company.

    Args:
        company_name: Company to enrich.
        context: Additional context dict.
        tool_assignments: Mapping of agent_name → list of tool_name strings.
    """
    ctx = context or {}
    assignments = tool_assignments or {}
    llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0, model_kwargs={"seed": 42})
    # llm = ChatOpenAI(
    #     model=settings.groq_model,  # Groq model
    #     api_key=settings.groq_api_key,
    #     base_url=settings.groq_base_url,
    #     temperature=0
    # )

    # ── Create agents and tasks ──
    agents = []
    tasks = []
    for agent_name, entry in AGENT_REGISTRY.items():
        agent_tool_names = assignments.get(agent_name, [])
        logger.info("[%s] Tool names from DB config: %s", agent_name, agent_tool_names)
        agent_tools = resolve_tools(agent_tool_names)
        resolved_names = [getattr(t, 'name', str(t)) for t in agent_tools]
        logger.info("[%s] Resolved %d/%d tools: %s", agent_name, len(agent_tools), len(agent_tool_names), resolved_names)
        if len(agent_tools) != len(agent_tool_names):
            missing = set(agent_tool_names) - set(resolved_names)
            logger.warning("[%s] Tools NOT found in registry: %s", agent_name, missing)

        agent = entry["create"](tools=agent_tools, llm=llm)
        task_kwargs = {
            "description": entry["build_prompt"](prompt_generator, company_name, ctx),
            "expected_output": entry["expected_output"],
            "agent": agent,
        }
        if "output_json" in entry:
            task_kwargs["output_json"] = entry["output_json"]
        task = Task(**task_kwargs)
        agents.append(agent)
        tasks.append(task)

    # ── Aggregation agent always runs (no external tools) ──
    aggregation_agent = create_aggregation_agent(llm=llm)
    sources = {name.replace("_agent", ""): True for name in AGENT_REGISTRY}
    aggregation_task = Task(
        description=prompt_generator.build_aggregation_prompt(company_name, sources),
        expected_output="Single JSON object matching the EnrichedLead schema with contacts, news, financials, executive summary, and overall confidence",
        agent=aggregation_agent,
        context=tasks,
    )
    agents.append(aggregation_agent)
    tasks.append(aggregation_task)

    # ── Assemble crew ──
    crew = Crew(
        agents=agents,
        tasks=tasks,
        process=Process.sequential,
        verbose=True,
    )

    return crew
