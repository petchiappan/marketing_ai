"""Pydantic output schemas for the Financial Agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CompanyProfile(BaseModel):
    """Core firmographic profile of the target company."""

    industry: str = Field(..., description="Industry vertical, e.g. SaaS, FinTech")
    revenue_range_usd: str = Field("", description="Estimated revenue range in USD, e.g. 50M-100M")
    employee_count: int = Field(0, description="Total number of employees")
    employee_growth_percent: float = Field(0.0, description="Year-over-year employee growth percentage")
    funding_stage: str = Field("", description="Latest funding stage, e.g. Series B, Series C")
    headquarters_country: str = Field("", description="Country where HQ is located")
    founded_year: int = Field(0, description="Year the company was founded")


class FinancialAgentData(BaseModel):
    """Payload containing the financial / firmographic analysis."""

    company_profile: CompanyProfile = Field(..., description="Company firmographic profile")
    firmographic_score: int = Field(0, ge=0, le=100, description="Firmographic fit score (0-100)")
    growth_score: int = Field(0, ge=0, le=100, description="Growth trajectory score (0-100)")
    industry_match_score: int = Field(0, ge=0, le=100, description="Industry match relevance score (0-100)")


class SourceMetadata(BaseModel):
    """Metadata about the data provider used."""

    provider: str = Field(..., description="Provider name")
    api_version: str = Field("", description="API version used")
    timestamp_utc: str = Field("", description="UTC timestamp of the API call")


class FinancialAgentOutput(BaseModel):
    """
    Structured JSON output schema for the financial_agent.

    CrewAI will enforce that the agent returns data matching this schema
    when used with ``output_json=FinancialAgentOutput`` on the Task.
    """

    request_id: str = Field(..., description="Unique request identifier")
    lead_id: str = Field(..., description="Salesforce lead ID")
    agent_name: str = Field("financial_agent", description="Name of the agent")
    status: str = Field("success", description="Execution status")
    execution_time_ms: int = Field(0, description="Execution time in milliseconds")
    data: FinancialAgentData = Field(..., description="Financial data payload")
    errors: list[str] = Field(default_factory=list, description="List of errors, if any")
    confidence_score: float = Field(0.0, ge=0.0, le=1.0, description="Overall confidence score")
    source_metadata: SourceMetadata = Field(..., description="Source provider metadata")
