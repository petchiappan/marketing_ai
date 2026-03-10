"""Pydantic output schemas for the Contact Agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ContactFound(BaseModel):
    """A single contact discovered by the contact agent."""

    full_name: str = Field(..., description="Full name of the contact")
    title: str = Field(..., description="Job title")
    department: str = Field(..., description="Department the contact belongs to")
    seniority_level: Literal["C-Level", "VP", "Director", "Manager", "Other"] = Field(
        ..., description="Seniority level"
    )
    email: str = Field(..., description="Business email address")
    email_verification_status: Literal["verified", "unverified"] = Field(
        "unverified", description="Email verification status"
    )
    linkedin_url: str = Field("", description="LinkedIn profile URL")
    decision_maker_score: int = Field(0, ge=0, le=100, description="Decision-maker relevance score (0-100)")
    contact_quality_score: int = Field(0, ge=0, le=100, description="Overall contact quality score (0-100)")
    confidence_score: float = Field(0.0, ge=0.0, le=1.0, description="Confidence score between 0 and 1")
    source: str = Field(..., description="Data source, e.g. Lusha, Apollo")


class ContactAgentData(BaseModel):
    """Payload containing the discovered contacts."""

    contacts_found: list[ContactFound] = Field(
        default_factory=list, description="List of contacts discovered"
    )
    total_contacts_found: int = Field(0, description="Total number of contacts found")
    decision_makers_identified: int = Field(
        0, description="Number of decision-makers identified"
    )


class SourceMetadata(BaseModel):
    """Metadata about the data provider used."""

    provider: str = Field(..., description="Provider name")
    api_version: str = Field("", description="API version used")
    timestamp_utc: str = Field("", description="UTC timestamp of the API call")


class ContactAgentOutput(BaseModel):
    """
    Structured JSON output schema for the contact_agent.

    CrewAI will enforce that the agent returns data matching this schema
    when used with ``output_json=ContactAgentOutput`` on the Task.
    """

    request_id: str = Field(..., description="Unique request identifier")
    lead_id: str = Field(..., description="Salesforce lead ID")
    agent_name: str = Field("contact_agent", description="Name of the agent")
    status: str = Field("success", description="Execution status")
    execution_time_ms: int = Field(0, description="Execution time in milliseconds")
    data: ContactAgentData = Field(..., description="Contact data payload")
    errors: list[str] = Field(default_factory=list, description="List of errors, if any")
    confidence_score: float = Field(0.0, ge=0.0, le=1.0, description="Overall confidence score")
    source_metadata: SourceMetadata = Field(..., description="Source provider metadata")
