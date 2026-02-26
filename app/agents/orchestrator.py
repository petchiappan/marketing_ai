"""CrewAI orchestrator – coordinates enrichment agents with tool-specific access."""

from __future__ import annotations

from crewai import Crew, Process, Task
from langchain_openai import ChatOpenAI

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
        "expected_output": "JSON array of contact objects with name, title, email, phone, linkedin_url, confidence_score",
    },
    "news_agent": {
        "create": create_news_agent,
        "build_prompt": lambda pg, company, ctx: pg.build_news_prompt(company, ctx),
        "expected_output": "JSON array of news objects with headline, summary, url, published_date, sentiment, relevance_score, category",
    },
    "financial_agent": {
        "create": create_financial_agent,
        "build_prompt": lambda pg, company, ctx: pg.build_financial_prompt(company, ctx),
        "expected_output": "JSON object with revenue, funding_total, market_cap, employee_count, industry, headquarters, confidence_score",
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
    llm = ChatOpenAI(model="gpt-4.1-mini")

    # ── Create agents and tasks ──
    agents = []
    tasks = []
    for agent_name, entry in AGENT_REGISTRY.items():
        agent_tool_names = assignments.get(agent_name, [])
        agent_tools = resolve_tools(agent_tool_names)

        agent = entry["create"](tools=agent_tools, llm=llm)
        task = Task(
            description=entry["build_prompt"](prompt_generator, company_name, ctx),
            expected_output=entry["expected_output"],
            agent=agent,
        )
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
