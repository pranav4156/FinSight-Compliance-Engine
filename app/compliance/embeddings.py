import logging
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import SARReport

logger = logging.getLogger(__name__)

_embeddings_model = None


def get_embeddings_model():
    global _embeddings_model
    if _embeddings_model is None:
        from langchain_openai import OpenAIEmbeddings
        _embeddings_model = OpenAIEmbeddings(
            model="text-embedding-3-small",
            openai_api_key=settings.openai_api_key,
        )
    return _embeddings_model


async def embed_text(text_content: str) -> list[float]:
    """Convert a text string into a 1536-dimensional vector."""
    model = get_embeddings_model()
    return await model.aembed_query(text_content)


async def find_similar_cases(
    narrative_text: str,
    tenant_id: UUID,
    session: AsyncSession,
    limit: int = 3,
) -> list[SARReport]:
    """
    Find the most similar past SAR reports using pgvector cosine similarity.

    When generating a new SAR, showing the LLM 2-3 similar past cases
    dramatically improves the quality and consistency of the narrative.

    Returns up to `limit` past SARs ordered by similarity to the query text.
    Returns [] if no past SARs exist yet (handles edge case #29 — cold start).
    """
    try:
        query_vector = await embed_text(narrative_text)
        vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"

        result = await session.execute(
            text(
                "SELECT * FROM sar_reports "
                "WHERE tenant_id = :tenant_id "
                "AND narrative_embedding IS NOT NULL "
                "ORDER BY narrative_embedding <-> :embedding "
                "LIMIT :limit"
            ),
            {
                "tenant_id": str(tenant_id),
                "embedding": vector_str,
                "limit": limit,
            },
        )
        rows = result.fetchall()

        similar = []
        for row in rows:
            sar = SARReport(
                id=row.id,
                narrative=row.narrative,
                created_at=row.created_at,
            )
            similar.append(sar)
        return similar

    except Exception as e:
        logger.warning(f"Similar case search failed (non-critical): {e}")
        return []


async def store_embedding(sar_id: UUID, narrative: str, session: AsyncSession) -> None:
    """
    Generate and store the embedding for a newly created SAR report.
    This enables future similarity searches.
    """
    try:
        vector = await embed_text(narrative)
        vector_str = "[" + ",".join(str(v) for v in vector) + "]"

        await session.execute(
            text(
                "UPDATE sar_reports SET narrative_embedding = :embedding WHERE id = :id"
            ),
            {"embedding": vector_str, "id": str(sar_id)},
        )
        await session.commit()
    except Exception as e:
        logger.warning(f"Embedding storage failed (non-critical): {e}")
