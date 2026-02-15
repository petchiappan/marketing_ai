"""Signal Hire API tool for CrewAI – fetches contact information."""

from __future__ import annotations

from crewai.tools import tool


@tool("Search Signal Hire for contacts")
def search_signal_hire(company_name: str) -> str:
    """
    Search the Signal Hire API for contacts at the given company.

    Returns a JSON string of contact records including name, title,
    email, phone, and LinkedIn URL. Each record includes a
    confidence_score and source_tool='signal_hire'.
    """
    return (
        f'{{"source_tool": "signal_hire", "company": "{company_name}", '
        f'"contacts": [], "note": "Placeholder – configure Signal Hire API key in admin panel"}}'
    )
