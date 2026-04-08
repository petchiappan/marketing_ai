"""Pydantic validation schemas for Fallback Extraction Phase."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class FallbackRecoveryData(BaseModel):
    """
    Strict Salesforce-bound schema. 
    The fast extractor LLM must conform to these types strictly.
    """
    ceo_email: Optional[str] = Field(default=None, description="The validated business email for the CEO")
    company_phone_number: Optional[str] = Field(default=None, description="The primary business phone number")
    revenue: Optional[int] = Field(default=None, description="Annual recurring revenue in USD")
    employee_count: Optional[int] = Field(default=None, description="Number of employees")
    recent_company_news: Optional[list[str]] = Field(default=None, description="Recent important news headlines about the company")
