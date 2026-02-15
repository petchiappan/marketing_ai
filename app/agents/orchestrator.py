"""CrewAI orchestrator – coordinates parallel enrichment and aggregation."""

from __future__ import annotations

from crewai import Crew, Process, Task

from app.agents.contact_agent import create_contact_agent
from app.agents.news_agent import create_news_agent
from app.agents.financial_agent import create_financial_agent
from app.agents.aggregation_agent import create_aggregation_agent
from app.infrastructure.prompt_generator import prompt_generator


def build_enrichment_crew(company_name: str, context: dict | None = None) -> Crew:
    """
    Build a CrewAI Crew for enriching a single company.

    Stage 2 agents (contact, news, financial) run in parallel.
    The aggregation agent runs sequentially after all three complete.
    """
    ctx = context or {}

    # ── Create agents ──
    contact_agent = create_contact_agent()
    news_agent = create_news_agent()
    financial_agent = create_financial_agent()
    aggregation_agent = create_aggregation_agent()

    # ── Build tasks with dynamic prompts ──
    contact_task = Task(
        description=prompt_generator.build_contact_prompt(company_name, ctx),
        expected_output="JSON array of contact objects with name, title, email, phone, linkedin_url, confidence_score",
        agent=contact_agent,
    )

    news_task = Task(
        description=prompt_generator.build_news_prompt(company_name, ctx),
        expected_output="JSON array of news objects with headline, summary, url, published_date, sentiment, relevance_score, category",
        agent=news_agent,
    )

    financial_task = Task(
        description=prompt_generator.build_financial_prompt(company_name, ctx),
        expected_output="JSON object with revenue, funding_total, market_cap, employee_count, industry, headquarters, confidence_score",
        agent=financial_agent,
    )

    aggregation_task = Task(
        description=prompt_generator.build_aggregation_prompt(company_name, {
            "contact": True,
            "news": True,
            "financial": True,
        }),
        expected_output="Single JSON object matching the EnrichedLead schema with contacts, news, financials, executive summary, and overall confidence",
        agent=aggregation_agent,
        context=[contact_task, news_task, financial_task],
    )

    # ── Assemble crew ──
    crew = Crew(
        agents=[contact_agent, news_agent, financial_agent, aggregation_agent],
        tasks=[contact_task, news_task, financial_task, aggregation_task],
        process=Process.sequential,  # Tasks execute in order; first 3 can be parallelized via async
        verbose=True,
    )

    return crew
