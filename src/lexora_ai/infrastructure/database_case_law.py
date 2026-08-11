from __future__ import annotations

import asyncio

from lexora_ai.case_law_context import rank_case_law
from lexora_ai.db.session import SessionFactory
from lexora_ai.db.unit_of_work import LexoraUnitOfWork
from lexora_ai.domain import CaseLawChunk

_LEXICAL_CORPUS_LIMIT = 10_000
_LOCAL_VECTOR_SCAN_LIMIT = 500
_MAX_RETRIEVAL_TOP_K = 50
_SEARCH_CONCURRENCY = 4


class DatabaseCaseLawKnowledgePort:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._search_semaphore = asyncio.Semaphore(_SEARCH_CONCURRENCY)

    async def search(
        self,
        query: str,
        *,
        query_embedding: tuple[float, ...] | None,
        embedding_model: str | None,
        top_k: int = 5,
    ) -> list[CaseLawChunk]:
        if top_k <= 0:
            return []
        if top_k > _MAX_RETRIEVAL_TOP_K:
            raise ValueError(f"top_k must not exceed {_MAX_RETRIEVAL_TOP_K}")
        async with self._search_semaphore:
            return await self._search(
                query,
                query_embedding=query_embedding,
                embedding_model=embedding_model,
                top_k=top_k,
            )

    async def _search(
        self,
        query: str,
        *,
        query_embedding: tuple[float, ...] | None,
        embedding_model: str | None,
        top_k: int,
    ) -> list[CaseLawChunk]:
        async with self._session_factory() as session:
            repository = LexoraUnitOfWork(session).case_law
            postgres = session.get_bind().dialect.name == "postgresql"
            vector_search = query_embedding is not None and embedding_model is not None
            if not postgres or not vector_search:
                scan_limit = (
                    _LOCAL_VECTOR_SCAN_LIMIT
                    if vector_search
                    else _LEXICAL_CORPUS_LIMIT
                )
                chunks = await repository.list_approved_chunks(
                    include_embeddings=vector_search,
                    limit=scan_limit + 1,
                )
                if len(chunks) > scan_limit:
                    raise RuntimeError(
                        "case-law retrieval corpus exceeds the bounded in-process scan limit"
                    )
                return rank_case_law(
                    query,
                    chunks,
                    query_embedding=query_embedding,
                    embedding_model=embedding_model,
                    top_k=top_k,
                )

            candidate_k = max(top_k * 3, top_k)
            lightweight_chunks = await repository.list_approved_chunks(
                include_embeddings=False,
                limit=_LEXICAL_CORPUS_LIMIT + 1,
            )
            if len(lightweight_chunks) > _LEXICAL_CORPUS_LIMIT:
                raise RuntimeError(
                    "case-law retrieval corpus exceeds the bounded lexical scan limit"
                )
            lexical_candidates = rank_case_law(
                query,
                lightweight_chunks,
                query_embedding=None,
                embedding_model=None,
                top_k=candidate_k,
            )
            vector_candidate_ids = await repository.list_approved_vector_candidate_ids(
                query_embedding,
                embedding_model,
                limit=candidate_k,
            )
            if not vector_candidate_ids:
                return lexical_candidates[:top_k]
            candidate_ids = list(
                dict.fromkeys(
                    [chunk.id for chunk in lexical_candidates] + vector_candidate_ids
                )
            )
            chunks = await repository.list_approved_chunks(chunk_ids=candidate_ids)
        return rank_case_law(
            query,
            chunks,
            query_embedding=query_embedding,
            embedding_model=embedding_model,
            top_k=top_k,
        )
