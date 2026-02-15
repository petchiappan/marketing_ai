"""Apollo.io API tool for CrewAI – fetches contact information."""

from __future__ import annotations

from crewai.tools import tool


@tool("Search Apollo for contacts")
def search_apollo(company_name: str) -> str:
    """
    Search the Apollo.io API for contacts at the given company.

    Returns a JSON string of contact records including name, title,
    email, phone, and LinkedIn URL. Each record includes a
    confidence_score and source_tool='apollo'.

    NOTE: Replace the placeholder implementation below with actual
    Apollo API calls once API credentials are configured in the admin panel.
    """
    return (
        f'{{"source_tool": "apollo", "company": "{company_name}", '
        f'"contacts": [], "note": "Placeholder – configure Apollo API key in admin panel"}}'
    )
