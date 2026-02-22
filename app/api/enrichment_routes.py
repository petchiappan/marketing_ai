"""Enrichment API – accepts lead enrichment requests and returns results."""

from __future__ import annotations

import traceback
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repository as repo
from app.db.session import get_db

router = APIRouter(prefix="/api/enrich", tags=["enrichment"])


# ── Request / Response schemas ──

class EnrichmentRequestIn(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=500)
    source: str = Field(default="api", pattern="^(salesforce|web_form|api)$")
    salesforce_lead_id: str | None = None
    additional_fields: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = None


class EnrichmentRequestOut(BaseModel):
    id: str
    company_name: str
    status: str
    message: str


class EnrichedLeadOut(BaseModel):
    id: str
    company_name: str
    industry: str | None = None
    headquarters: str | None = None
    employee_count: int | None = None
    contacts: list[Any] = []
    revenue: float | None = None
    funding_total: float | None = None
    recent_news: list[Any] = []
    overall_confidence: float | None = None
    enrichment_summary: str | None = None


# ── Endpoints ──

@router.post("/", response_model=EnrichmentRequestOut, status_code=status.HTTP_202_ACCEPTED)
async def create_enrichment_request(
    body: EnrichmentRequestIn,
    db: AsyncSession = Depends(get_db),
):
    """Submit a new enrichment request (async processing)."""
    req = await repo.create_request(
        db,
        company_name=body.company_name,
        source=body.source,
        salesforce_lead_id=body.salesforce_lead_id,
        additional_fields=body.additional_fields,
        requested_by=body.requested_by,
    )
    return EnrichmentRequestOut(
        id=str(req.id),
        company_name=req.company_name,
        status=req.status,
        message="Enrichment request queued for processing.",
    )


@router.get("/{request_id}/status")
async def get_enrichment_status(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Check the status of an enrichment request."""
    req = await repo.get_request(db, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    return {
        "id": str(req.id),
        "company_name": req.company_name,
        "status": req.status,
        "created_at": req.created_at.isoformat(),
    }


@router.get("/{request_id}/result", response_model=EnrichedLeadOut)
async def get_enrichment_result(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve the enriched lead data for a completed request."""
    lead = await repo.get_enriched_lead(db, request_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Enriched data not available yet")
    return EnrichedLeadOut(
        id=str(lead.id),
        company_name=lead.company_name,
        industry=lead.industry,
        headquarters=lead.headquarters,
        employee_count=lead.employee_count,
        contacts=lead.contacts or [],
        revenue=float(lead.revenue) if lead.revenue else None,
        funding_total=float(lead.funding_total) if lead.funding_total else None,
        recent_news=lead.recent_news or [],
        overall_confidence=float(lead.overall_confidence) if lead.overall_confidence else None,
        enrichment_summary=lead.enrichment_summary,
    )


@router.get("/", response_model=list[dict])
async def list_enrichment_requests(
    limit: int = 50,
    offset: int = 0,
    status_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List enrichment requests with optional status filter."""
    requests = await repo.list_requests(db, limit=limit, offset=offset, status=status_filter)
    return [
        {
            "id": str(r.id),
            "company_name": r.company_name,
            "source": r.source,
            "status": r.status,
            "requested_by": r.requested_by,
            "created_at": r.created_at.isoformat(),
        }
        for r in requests
    ]
