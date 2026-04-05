"""Lusha API tool for CrewAI – fetches contact information."""

from __future__ import annotations

import json
import logging

import httpx
from crewai.tools import tool

from app.config.settings import settings
from app.db.repository import get_tool_config

logger = logging.getLogger(__name__)

# Lusha API defaults
_DEFAULT_BASE_URL = "https://api.lusha.com/prospecting"
_CONTACT_SEARCH_PATH = "/contact/search"
_TIMEOUT_SECONDS = 30
_MAX_RESULTS = 25


async def _get_lusha_config() -> tuple[str, str]:
    """Check DB for enablement and fetch Lusha API key/URL from env.

    Returns:
        (api_key, base_url)

    Raises:
        RuntimeError: if the tool is disabled or missing env API key.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(settings.database_url, pool_size=1, max_overflow=0)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with factory() as db:
            config = await get_tool_config(db, "lusha")

        if config and not config.is_enabled:
            raise RuntimeError("Lusha tool is disabled in the admin panel.")

        # Resolve secrets from environment
        env_config = settings.get_tool_config("lusha")
        api_key = env_config.get("api_key")
        base_url = env_config.get("base_url") or _DEFAULT_BASE_URL

        if not api_key:
            raise RuntimeError(
                "Lusha API key is missing from environment variables (TOOL_LUSHA_API_KEY)."
            )

        return api_key, base_url.rstrip("/")
    finally:
        await engine.dispose(close=False)


def _build_search_payload(
    company_name: str,
    domain: str = "",
    limit: int = _MAX_RESULTS,
) -> dict:
    """Build the JSON request body for Lusha /prospecting/contact/search."""

    return {
        {
            "pages": {
                "page": 0,
                "size": 20
            },
            "filters": {
                "contacts": {
                    "include": {
                        "departments": [
                            "Engineering & Technical",
                            "Marketing"
                        ],
                        "seniority": [
                            "4",
                            "5"
                        ],
                        "existing_data_points": [
                            "phone",
                            "work_email",
                            "mobile_phone"
                        ]
                    },
                    "exclude": {
                        "departments": [
                        "Human Resources"
                        ]
                    }
                },
                "companies": {
                    "include": {
                        "names": [company_name],
                        "mainIndustriesIds": [4,5],
                        "subIndustriesIds": [101],
                        "intentTopics": ["Digital Sales"],
                        "sizes": [
                        {
                            "min": 100,
                            "max": 1000
                        }
                        ],
                        "revenues": [
                        {
                            "min": 10000000,
                            "max": 100000000
                        }
                        ],
                        "sicCodes": [
                            "1011",
                            "1021"
                        ],
                        "naicsCodes": [
                            "11",
                        "21"
                        ]
                    },
                    "exclude": {}
                }
            }
        }
    }


def _normalize_contacts(raw_data: dict, company_name: str) -> list[dict]:
    """Extract and normalize contact records from the Lusha API response."""
    contacts = []
    for entry in raw_data.get("data", []):
        contact = {
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

        # Emails – pick the first available
        emails = entry.get("emails", [])
        if emails:
            contact["email"] = (
                emails[0] if isinstance(emails[0], str)
                else emails[0].get("email", "")
            )

        # Phones – pick the first available
        phones = entry.get("phoneNumbers", [])
        if phones:
            contact["phone"] = (
                phones[0] if isinstance(phones[0], str)
                else phones[0].get("number", "")
            )

        contacts.append(contact)

    return contacts


@tool("Search Lusha for contacts")
def search_lusha(company_name: str) -> str:
    """
    Search the Lusha API for contacts at the given company.

    Returns a JSON string of contact records including name, title,
    email, phone, and LinkedIn URL. Each record includes
    source_tool='lusha'.
    """
    import asyncio

    try:
        api_key, base_url = asyncio.run(_get_lusha_config())
    except RuntimeError as exc:
        return json.dumps({
            "source_tool": "lusha",
            "company": company_name,
            "contacts": [],
            "error": str(exc),
        })

    url = f"{base_url}{_CONTACT_SEARCH_PATH}"
    headers = {
        "api_key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = _build_search_payload(company_name)

    # Log full request details
    logger.info("Lusha API request: POST %s", url)
    logger.debug("Lusha request headers: %s", {k: (v[:4] + "****" if k == "api_key" else v) for k, v in headers.items()})
    logger.debug("Lusha request payload: %s", json.dumps(payload, indent=2))

    try:
        with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
            resp = client.post(url, headers=headers, json=payload)

            # Log full response regardless of status
            logger.info(
                "Lusha API response: status=%s, content_length=%s",
                resp.status_code, len(resp.text),
            )
            logger.debug("Lusha response headers: %s", dict(resp.headers))
            logger.info("Lusha response body: %s", resp.text[:2000])

            resp.raise_for_status()
            raw = resp.json()

        contacts = _normalize_contacts(raw, company_name)

        return json.dumps({
            "source_tool": "lusha",
            "company": company_name,
            "contacts": contacts,
            "total_returned": len(contacts),
        })

    except httpx.HTTPStatusError as exc:
        error_body = exc.response.text
        logger.error(
            "Lusha API HTTP error for '%s': status=%s, url=%s, response_body=%s",
            company_name, exc.response.status_code, url, error_body[:2000],
        )
        return json.dumps({
            "source_tool": "lusha",
            "company": company_name,
            "contacts": [],
            "error": f"Lusha API returned {exc.response.status_code}",
            "detail": error_body[:2000],
        })

    except httpx.TimeoutException:
        logger.error("Lusha API timeout for %s", company_name)
        return json.dumps({
            "source_tool": "lusha",
            "company": company_name,
            "contacts": [],
            "error": f"Lusha API timed out after {_TIMEOUT_SECONDS}s",
        })

    except Exception as exc:
        logger.exception("Unexpected Lusha error for %s", company_name)
        return json.dumps({
            "source_tool": "lusha",
            "company": company_name,
            "contacts": [],
            "error": f"Unexpected error: {type(exc).__name__}: {exc}",
        })
