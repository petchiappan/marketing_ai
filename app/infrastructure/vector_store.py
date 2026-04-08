"""Vector store utilities for generating and managing embeddings."""

import logging
from typing import List

from langchain_openai import OpenAIEmbeddings

from app.config.settings import settings

logger = logging.getLogger(__name__)

# Cache the embeddings client
_embeddings_client = None

def get_embeddings_client() -> OpenAIEmbeddings:
    """Get or create the OpenAI Embeddings client."""
    global _embeddings_client
    if _embeddings_client is None:
        _embeddings_client = OpenAIEmbeddings(
            model="text-embedding-3-small",
            # Ensure the api key is correctly pulled, Langchain usually checks OPENAI_API_KEY env var
            # or we can pass it explicitly if it's in settings under a different name.
            api_key=settings.get_tool_config("openai").get("api_key") if settings.get_tool_config("openai") else None
        )
    return _embeddings_client

async def generate_embedding(text: str) -> List[float]:
    """Generate a vector embedding for the given text using OpenAI."""
    try:
        client = get_embeddings_client()
        # aembed_query is the async method for a single string in Langchain
        embedding = await client.aembed_query(text)
        return embedding
    except Exception as e:
        logger.error("Failed to generate embedding: %s", e)
        # Return a zero vector or raise depending on preference.
        # Returning an empty list might break pgvector, so we raise.
        raise
