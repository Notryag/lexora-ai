from __future__ import annotations

from lexora_ai.case_law_context import rank_case_law
from lexora_ai.db.session import SessionFactory
from lexora_ai.db.unit_of_work import LexoraUnitOfWork
from lexora_ai.domain import CaseLawChunk


class DatabaseCaseLawKnowledgePort:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def search(
        self,
        query: str,
        *,
        query_embedding: tuple[float, ...] | None,
        embedding_model: str | None,
        top_k: int = 5,
    ) -> list[CaseLawChunk]:
        async with self._session_factory() as session:
            chunks = await LexoraUnitOfWork(session).case_law.list_approved_chunks()
        return rank_case_law(
            query,
            chunks,
            query_embedding=query_embedding,
            embedding_model=embedding_model,
            top_k=top_k,
        )
