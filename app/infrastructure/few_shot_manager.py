"""Few-shot prompt bank manager.

Retrieves high-rated user feedback examples from the database
and injects them into LLM prompts to improve output quality.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repository as repo

logger = logging.getLogger(__name__)


class FewShotManager:
    """Manages the few-shot prompt bank backed by the few_shot_examples DB table."""

    async def get_examples(
        self,
        db: AsyncSession,
        limit: int = 3,
        min_rating: int = 4,
        query_text: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get top-rated, most recent few-shot examples (with optional semantic search)."""
        query_embedding = None
        if query_text:
            from app.infrastructure.vector_store import generate_embedding
            try:
                query_embedding = await generate_embedding(query_text)
            except Exception as e:
                logger.warning("Failed to generate embedding for few_shot_manager: %s", e)
                
        return await repo.get_few_shot_examples(
            db, 
            limit=limit, 
            min_rating=min_rating,
            query_embedding=query_embedding
        )

    def inject_into_prompt(
        self,
        base_prompt: str,
        examples: list[dict[str, Any]],
    ) -> str:
        """Inject few-shot examples into an LLM prompt.

        Appends high-rated past outputs as reference examples
        so the LLM can match the expected quality and format.
        """
        if not examples:
            return base_prompt

        examples_text = "\n\n".join(
            [
                f"### Example {i + 1} (Rating: {ex['rating']}/5)\n"
                f"**Company:** {ex['company_name']}\n"
                f"**Output:**\n{ex['output_response'][:2000]}"
                for i, ex in enumerate(examples)
            ]
        )

        return (
            f"{base_prompt}\n\n"
            f"## High-Quality Reference Examples (match this quality):\n"
            f"{examples_text}"
        )
