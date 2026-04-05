"""API routes for user feedback and output enhancement.

Endpoints:
- POST /api/enrich/{request_id}/feedback — Submit user rating (1-5 stars)
- POST /api/enrich/{request_id}/enhance  — Re-prompt LLM with user instructions
- GET  /api/enrich/{request_id}/feedback — Get feedback for a request
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repository as repo
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/enrich", tags=["feedback"])


# ── Request/Response Schemas ──────────────────────────────────────────────


class FeedbackIn(BaseModel):
    """Payload for submitting user feedback."""
    rating: int = Field(..., ge=1, le=5, description="Star rating 1-5")
    feedback_text: Optional[str] = Field(None, max_length=2000, description="Optional text feedback")
    rated_by: Optional[str] = Field(None, max_length=255, description="Email of person rating")


class FeedbackOut(BaseModel):
    """Response after submitting feedback."""
    status: str
    promoted_to_few_shot: bool
    feedback_id: str


class EnhanceIn(BaseModel):
    """Payload for the Enhance button."""
    instructions: Optional[str] = Field(
        None,
        max_length=2000,
        description="Optional user instructions for improvement",
    )


class EnhanceOut(BaseModel):
    """Response after enhancing output."""
    request_id: str
    enhanced_output: str
    enhancement_id: str


class FeedbackDetail(BaseModel):
    """Feedback detail for GET response."""
    id: str
    rating: int
    feedback_text: Optional[str]
    rated_by: Optional[str]
    created_at: Optional[str]


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.post("/{request_id}/feedback", response_model=FeedbackOut)
async def submit_feedback(
    request_id: UUID,
    body: FeedbackIn,
    db: AsyncSession = Depends(get_db),
):
    """Submit user rating (1-5 ⭐) for an enrichment output.

    If rating >= 4, the output is automatically promoted to the
    few-shot prompt bank for future LLM quality improvement.
    """
    # Verify request exists
    req = await repo.get_request(db, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Enrichment request not found")

    # Save feedback
    feedback = await repo.save_feedback(
        db,
        request_id=request_id,
        rating=body.rating,
        feedback_text=body.feedback_text,
        rated_by=body.rated_by,
    )

    # Auto-promote to few-shot bank if rating >= 4
    promoted = False
    if body.rating >= 4:
        lead = await repo.get_enriched_lead(db, request_id)
        if lead and lead.enrichment_summary:
            await repo.promote_to_few_shot(
                db,
                request_id=request_id,
                company_name=req.company_name,
                output_response=lead.enrichment_summary,
                rating=body.rating,
            )
            promoted = True
            logger.info(
                "Feedback rating %d for %s — promoted to few-shot bank",
                body.rating, request_id,
            )

    await db.commit()

    return FeedbackOut(
        status="saved",
        promoted_to_few_shot=promoted,
        feedback_id=str(feedback.id),
    )


@router.get("/{request_id}/feedback", response_model=list[FeedbackDetail])
async def get_feedback(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get all feedback for a specific enrichment request."""
    feedbacks = await repo.get_feedback_for_request(db, request_id)
    return [
        FeedbackDetail(
            id=str(fb.id),
            rating=fb.rating,
            feedback_text=fb.feedback_text,
            rated_by=fb.rated_by,
            created_at=fb.created_at.isoformat() if fb.created_at else None,
        )
        for fb in feedbacks
    ]


@router.post("/{request_id}/enhance", response_model=EnhanceOut)
async def enhance_output(
    request_id: UUID,
    body: EnhanceIn,
    db: AsyncSession = Depends(get_db),
):
    """Re-prompt LLM with current output + user instructions to improve quality.

    The Enhance button allows users to iteratively refine the enrichment
    output by providing specific instructions (e.g., "add more contact details"
    or "focus on financial health").
    """
    from app.infrastructure.enhancer import llm_enhance

    # Get current enriched lead
    lead = await repo.get_enriched_lead(db, request_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Enriched lead not found")

    # Get few-shot examples for quality reference
    few_shots = await repo.get_few_shot_examples(db, limit=3, min_rating=4)

    # Run LLM enhancement
    enhanced = await llm_enhance(
        original_output=lead.enrichment_summary or "",
        user_instructions=body.instructions,
        few_shot_examples=few_shots,
    )

    # Save enhancement history (both original + enhanced)
    enhancement = await repo.save_enhancement(
        db,
        request_id=request_id,
        original_output=lead.enrichment_summary or "",
        enhanced_output=enhanced,
        user_instructions=body.instructions,
        enhancement_model="gpt-4.1-mini",
    )

    # Update the enriched lead with the enhanced output
    await repo.update_enrichment_summary(db, request_id, enhanced)

    await db.commit()

    logger.info("Enhanced output for %s — saved as enhancement %s", request_id, enhancement.id)

    return EnhanceOut(
        request_id=str(request_id),
        enhanced_output=enhanced,
        enhancement_id=str(enhancement.id),
    )
