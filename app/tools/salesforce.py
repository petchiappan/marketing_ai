"""Salesforce connector – reads leads and writes enriched data."""

from __future__ import annotations

from typing import Any

from crewai.tools import tool


@tool("Read Salesforce lead")
def read_salesforce_lead(lead_id: str) -> str:
    """
    Retrieve a Salesforce Lead record by its 18-character ID.

    Returns a JSON string of the lead's fields.
    """
    return (
        f'{{"source": "salesforce", "lead_id": "{lead_id}", '
        f'"data": {{}}, "note": "Placeholder – configure Salesforce credentials in admin panel"}}'
    )


def validate_for_salesforce(enriched_data: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Validate enriched data before writing to Salesforce.

    Returns (is_valid, list_of_errors).
    Checks: required fields, data types, character limits, email format.
    """
    import re

    errors: list[str] = []

    if not enriched_data.get("company_name"):
        errors.append("company_name is required")

    # Email validation for contacts
    email_re = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.]+$")
    for contact in enriched_data.get("contacts", []):
        email = contact.get("email")
        if email and not email_re.match(email):
            errors.append(f"Invalid email format: {email}")

    # Character limit checks (Salesforce default: 255)
    for field in ("company_name", "industry", "headquarters"):
        val = enriched_data.get(field, "")
        if val and len(val) > 255:
            errors.append(f"{field} exceeds 255 character limit ({len(val)} chars)")

    return len(errors) == 0, errors


async def sync_to_salesforce(
    lead_id: str,
    enriched_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update a Salesforce Lead with enriched data.

    In production, uses simple-salesforce:
        sf = Salesforce(...)
        sf.Lead.update(lead_id, mapped_fields)

    Returns a result dict with success status.
    """
    is_valid, errors = validate_for_salesforce(enriched_data)
    if not is_valid:
        return {"success": False, "errors": errors}

    # Placeholder – implement with simple-salesforce
    return {
        "success": True,
        "lead_id": lead_id,
        "note": "Placeholder – configure Salesforce credentials",
    }
