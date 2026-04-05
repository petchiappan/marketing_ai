"""Deterministic API data fetchers — direct httpx calls, NO LLM.

Each function makes a plain HTTP request and returns structured data.
Retries are handled by tenacity with exponential backoff.
The LLM NEVER calls these functions — they are invoked by workflow code.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Contact Data Fetchers
# ---------------------------------------------------------------------------

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError)),
)
async def fetch_lusha(company_name: str, config: dict[str, str]) -> dict[str, Any]:
    """Direct Lusha API call — deterministic, no LLM involvement."""
    base_url = (config.get("base_url") or "https://api.lusha.com").rstrip("/")
    url = f"{base_url}/prospecting/contact/search"

    payload = {
        "pages": {"page": 0, "size": 20},
        "filters": {
            "companies": {
                "include": {"names": [company_name]},
            }
        },
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
        resp = await client.post(
            url,
            headers={
                "api_key": config["api_key"],
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
        )
        logger.info("Lusha API: status=%s for '%s'", resp.status_code, company_name)
        resp.raise_for_status()
        data = resp.json()

    # Normalize into a common contact format
    contacts = []
    for entry in data.get("data", []):
        contact: dict[str, Any] = {
            "full_name": entry.get("fullName", ""),
            "first_name": entry.get("firstName", ""),
            "last_name": entry.get("lastName", ""),
            "title": entry.get("jobTitle", ""),
            "company": entry.get("companyName", company_name),
            "email": "",
            "phone": "",
            "linkedin_url": entry.get("socialLinks", {}).get("linkedin", ""),
            "source_tool": "lusha",
        }
        emails = entry.get("emails", [])
        if emails:
            contact["email"] = emails[0] if isinstance(emails[0], str) else emails[0].get("email", "")
        phones = entry.get("phoneNumbers", [])
        if phones:
            contact["phone"] = phones[0] if isinstance(phones[0], str) else phones[0].get("number", "")
        contacts.append(contact)

    return {"source": "lusha", "contacts": contacts, "total": len(contacts)}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError)),
)
async def fetch_apollo(company_name: str, config: dict[str, str]) -> dict[str, Any]:
    """Direct Apollo API call — deterministic, no LLM involvement."""
    base_url = (config.get("base_url") or "https://api.apollo.io").rstrip("/")
    url = f"{base_url}/v1/mixed_people/search"

    async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
        resp = await client.post(
            url,
            headers={
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "X-Api-Key": config["api_key"],
            },
            json={
                "q_organization_name": company_name,
                "per_page": 25,
                "person_titles": [
                    "CEO", "CTO", "CFO", "COO", "VP", "Director",
                    "Head of Engineering", "Head of Marketing",
                ],
            },
        )
        logger.info("Apollo API: status=%s for '%s'", resp.status_code, company_name)
        resp.raise_for_status()
        data = resp.json()

    contacts = []
    for person in data.get("people", []):
        contact: dict[str, Any] = {
            "full_name": person.get("name", ""),
            "first_name": person.get("first_name", ""),
            "last_name": person.get("last_name", ""),
            "title": person.get("title", ""),
            "company": person.get("organization", {}).get("name", company_name),
            "email": person.get("email", ""),
            "phone": "",
            "linkedin_url": person.get("linkedin_url", ""),
            "source_tool": "apollo",
        }
        phones = person.get("phone_numbers", [])
        if phones:
            contact["phone"] = phones[0].get("sanitized_number", "") if isinstance(phones[0], dict) else str(phones[0])
        contacts.append(contact)

    return {"source": "apollo", "contacts": contacts, "total": len(contacts)}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError)),
)
async def fetch_signal_hire(company_name: str, config: dict[str, str]) -> dict[str, Any]:
    """Direct SignalHire API call — deterministic, no LLM involvement."""
    base_url = (config.get("base_url") or "https://www.signalhire.com/api").rstrip("/")
    url = f"{base_url}/v1/candidate/search"

    async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
        resp = await client.post(
            url,
            headers={
                "apikey": config["api_key"],
                "Content-Type": "application/json",
            },
            json={"company": company_name, "limit": 20},
        )
        logger.info("SignalHire API: status=%s for '%s'", resp.status_code, company_name)
        resp.raise_for_status()
        data = resp.json()

    contacts = []
    for item in data.get("items", data.get("candidates", [])):
        contact: dict[str, Any] = {
            "full_name": item.get("name", item.get("fullName", "")),
            "first_name": item.get("firstName", ""),
            "last_name": item.get("lastName", ""),
            "title": item.get("title", item.get("currentPosition", "")),
            "company": company_name,
            "email": "",
            "phone": "",
            "linkedin_url": item.get("linkedinUrl", item.get("linkedin", "")),
            "source_tool": "signal_hire",
        }
        emails = item.get("emails", [])
        if emails:
            contact["email"] = emails[0] if isinstance(emails[0], str) else emails[0].get("value", "")
        phones = item.get("phones", [])
        if phones:
            contact["phone"] = phones[0] if isinstance(phones[0], str) else phones[0].get("value", "")
        contacts.append(contact)

    return {"source": "signal_hire", "contacts": contacts, "total": len(contacts)}


# ---------------------------------------------------------------------------
# News Data Fetcher
# ---------------------------------------------------------------------------

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError)),
)
async def fetch_news(company_name: str, config: dict[str, str]) -> dict[str, Any]:
    """Direct News Search API call — deterministic, no LLM involvement.

    Supports Bing News Search API format. Adjust for your provider.
    """
    base_url = (config.get("base_url") or "https://api.bing.microsoft.com").rstrip("/")
    url = f"{base_url}/v7.0/news/search"

    async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
        resp = await client.get(
            url,
            headers={"Ocp-Apim-Subscription-Key": config["api_key"]},
            params={"q": company_name, "count": 10, "freshness": "Month", "mkt": "en-US"},
        )
        logger.info("News API: status=%s for '%s'", resp.status_code, company_name)
        resp.raise_for_status()
        data = resp.json()

    articles = []
    for item in data.get("value", []):
        articles.append({
            "headline": item.get("name", ""),
            "summary": item.get("description", ""),
            "url": item.get("url", ""),
            "published_date": item.get("datePublished", ""),
            "source": item.get("provider", [{}])[0].get("name", "") if item.get("provider") else "",
            "category": item.get("category", "general"),
        })

    return {"source": "news_search", "articles": articles, "total": len(articles)}


# ---------------------------------------------------------------------------
# Financial Data Fetcher
# ---------------------------------------------------------------------------

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError)),
)
async def fetch_financial(company_name: str, config: dict[str, str]) -> dict[str, Any]:
    """Direct Financial Data API call — deterministic, no LLM involvement.

    Adjust endpoint/payload for your actual financial data provider
    (Yahoo Finance, Alpha Vantage, Crunchbase, etc.).
    """
    base_url = (config.get("base_url") or "https://api.example.com").rstrip("/")
    url = f"{base_url}/v1/company/search"

    async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
        resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {config['api_key']}"},
            params={"q": company_name},
        )
        logger.info("Financial API: status=%s for '%s'", resp.status_code, company_name)
        resp.raise_for_status()
        data = resp.json()

    return {
        "source": "financial_data",
        "financials": {
            "revenue": data.get("revenue"),
            "revenue_currency": data.get("revenue_currency", "USD"),
            "employee_count": data.get("employee_count"),
            "funding_total": data.get("funding_total"),
            "funding_round": data.get("latest_funding_round"),
            "market_cap": data.get("market_cap"),
            "industry": data.get("industry"),
            "headquarters": data.get("headquarters"),
        },
    }


# ---------------------------------------------------------------------------
# Fetcher Registry — maps tool_name → fetcher function
# ---------------------------------------------------------------------------

FETCHER_MAP: dict[str, Any] = {
    "lusha": fetch_lusha,
    "apollo": fetch_apollo,
    "signal_hire": fetch_signal_hire,
    "news_search": fetch_news,
    "financial_data": fetch_financial,
}
