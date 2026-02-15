"""Lusha API tool for CrewAI – fetches contact information."""

from __future__ import annotations

import httpx
from crewai.tools import tool


@tool("Search Lusha for contacts")
def search_lusha(company_name: str) -> str:
    """
    Search the Lusha API for contacts at the given company.

    Returns a JSON string of contact records including name, title,
    email, phone, and LinkedIn URL. Each record includes a
    confidence_score and source_tool='lusha'.

    NOTE: Replace the placeholder implementation below with actual
    Lusha API calls once API credentials are configured in the admin panel.
    """
    # ── Placeholder implementation ──
    # In production, this reads the API key from the tool_configs table
    # (decrypted) and calls the Lusha REST API.
    #
    # Example real implementation:
    #
    #   from app.db.repository import get_tool_config
    #   config = await get_tool_config(db, "lusha")
    #   api_key = decrypt(config.api_key_encrypted)
    #   async with httpx.AsyncClient() as client:
    #       resp = await client.get(
    #           f"{config.base_url}/v2/contacts",
    #           params={"company": company_name},
    #           headers={"Authorization": f"Bearer {api_key}"},
    #       )
    #       return resp.json()

    return (
        f'{{"source_tool": "lusha", "company": "{company_name}", '
        f'"contacts": [], "note": "Placeholder – configure Lusha API key in admin panel"}}'
    )
