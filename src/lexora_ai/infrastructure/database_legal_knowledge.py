from __future__ import annotations

from lexora_ai.db.session import SessionFactory
from lexora_ai.db.unit_of_work import LexoraUnitOfWork
from lexora_ai.domain import LegalKnowledgeChunk
from lexora_ai.legal_context import rank_legal_knowledge


class DatabaseLegalKnowledgePort:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def search(
        self,
        query: str,
        *,
        query_embedding: tuple[float, ...] | None,
        embedding_model: str | None,
        top_k: int = 6,
    ) -> list[LegalKnowledgeChunk]:
        async with self._session_factory() as session:
            chunks = await LexoraUnitOfWork(session).legal_sources.list_effective_chunks()
        return rank_legal_knowledge(
            query,
            chunks,
            query_embedding=query_embedding,
            embedding_model=embedding_model,
            top_k=top_k,
        )
