"""Financial data tool for CrewAI – retrieves company financials."""

from __future__ import annotations

from crewai.tools import tool


@tool("Fetch financial data")
def fetch_financial_data(company_name: str) -> str:
    """
    Retrieve financial statistics for the given company from
    Yahoo Finance, SEC EDGAR, Crunchbase, and similar sources.

    Returns a JSON string with revenue, funding, market_cap,
    employee_count, industry, headquarters, and confidence_score.
    """
    return (
        f'{{"source_tool": "yahoo_finance", "company": "{company_name}", '
        f'"financials": {{}}, "note": "Placeholder – configure Yahoo Finance API in admin panel"}}'
    )
