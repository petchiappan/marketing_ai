"""Salesforce synchronization service for enriched leads."""

import json
import logging
from typing import Any

import httpx

from app.config.settings import settings

logger = logging.getLogger(__name__)

async def sync_lead_to_salesforce(lead_data: dict[str, Any], salesforce_lead_id: str | None) -> bool:
    """Map enriched lead data to a generic JSON payload and send to Salesforce via webhook."""
    webhook_url = settings.salesforce_webhook_url
    if not webhook_url:
        logger.warning("SALESFORCE_WEBHOOK_URL is not set. Skipping Salesforce sync.")
        return False
        
    # Map the final_output data into a generic payload
    payload = {
        "status": "enriched",
        "enrichment_pipeline": "hybrid_v2",
        "company_name": lead_data.get("company_name"),
        "salesforce_lead_id": salesforce_lead_id,
        "executive_summary": lead_data.get("executive_summary", ""),
        "lead_scores": lead_data.get("lead_scores", {}),
        "raw_stats": {
            "contact_count": lead_data.get("raw_contact_count", 0),
            "news_count": lead_data.get("raw_news_count", 0),
        },
        "recovered_data": lead_data.get("fallback_recovered_data", {}),
        "enrichment_sources": lead_data.get("enrichment_source", {}),
        "merged_contacts": lead_data.get("merged_contacts", [])
    }
    
    # Optional direct data mappings
    if lead_data.get("company_phone_number"):
        payload["company_phone"] = lead_data.get("company_phone_number")
    if lead_data.get("ceo_email"):
        payload["ceo_email"] = lead_data.get("ceo_email")
        
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                webhook_url,
                json=payload,
                timeout=10.0,
                headers={"Authorization": f"Bearer {settings.salesforce_security_token}"} if settings.salesforce_security_token else {}
            )
            response.raise_for_status()
            logger.info("Successfully synced enriched lead data to Salesforce webhook for %s", lead_data.get("company_name"))
            return True
    except Exception as e:
        logger.error("Failed to sync lead payload to Salesforce webhook: %s", e)
        return False
