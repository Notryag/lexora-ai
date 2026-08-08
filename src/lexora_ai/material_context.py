from __future__ import annotations

from dataclasses import dataclass

from rag_core import (
    ChunkingPolicy,
    DocumentBlock,
    EmbeddedRetrievalDocument,
    HeuristicTokenEstimator,
    ParsedDocument,
    RecursiveFallbackSplitter,
    RetrievalDocument,
    fuse_retrieval_hits,
    rank_lexical_documents,
    rank_vector_documents,
)

from lexora_ai.domain import CaseMaterial

LEXORA_SUBMITTED_MATERIAL_POLICY = ChunkingPolicy(
    name="lexora_submitted_material_v1",
    version="lexora-submitted-material-v1",
    target_tokens=450,
    max_tokens=700,
    min_tokens=80,
)
LEXORA_MATERIAL_RETRIEVAL_TOP_K = 8
LEXORA_QUERY_STOP_TERMS = {
    "一下",
    "什么",
    "应该",
    "怎么",
    "怎样",
    "情况",
    "怎么办",
    "我的",
    "这个",
}


@dataclass(frozen=True, slots=True)
class MaterialContextChunk:
    reference: str
    material_id: str
    title: str
    kind: str
    source_note: str | None
    content: str
    page_start: int | None
    page_end: int | None
    embedding: tuple[float, ...] | None = None
    embedding_model: str | None = None


def build_material_context(materials: list[CaseMaterial]) -> list[MaterialContextChunk]:
    splitter = RecursiveFallbackSplitter()
    estimator = HeuristicTokenEstimator()
    context: list[MaterialContextChunk] = []
    for material_index, material in enumerate(materials, start=1):
        document = ParsedDocument(
            file_name=material.title,
            mime_type=None,
            adapter="lexora-submitted-text",
            adapter_version="v1",
            title=material.title,
            blocks=(
                DocumentBlock(
                    id=str(material.material_id),
                    content=material.content,
                    block_type=material.kind.value,
                ),
            ),
        )
        chunks = splitter.split(document, LEXORA_SUBMITTED_MATERIAL_POLICY, estimator)
        for chunk_index, chunk in enumerate(chunks, start=1):
            context.append(
                MaterialContextChunk(
                    reference=f"M{material_index}:C{chunk_index}",
                    material_id=str(material.material_id),
                    title=material.title,
                    kind=material.kind.value,
                    source_note=material.source_note,
                    content=chunk.content,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                )
            )
    return context


def retrieve_material_context(
    query: str,
    materials: list[CaseMaterial],
    *,
    top_k: int = LEXORA_MATERIAL_RETRIEVAL_TOP_K,
) -> list[MaterialContextChunk]:
    chunks = build_material_context(materials)
    return rank_material_context(query, chunks, top_k=top_k)


def rank_material_context(
    query: str,
    chunks: list[MaterialContextChunk],
    *,
    top_k: int = LEXORA_MATERIAL_RETRIEVAL_TOP_K,
    query_embedding: tuple[float, ...] | None = None,
    embedding_model: str | None = None,
) -> list[MaterialContextChunk]:
    chunks_by_reference = {chunk.reference: chunk for chunk in chunks}
    candidates = [
        RetrievalDocument(
            id=chunk.reference,
            content=chunk.content,
            metadata={
                "material_id": chunk.material_id,
                "title": chunk.title,
                "kind": chunk.kind,
            },
        )
        for chunk in chunks
    ]
    lexical_hits = rank_lexical_documents(
        query,
        candidates,
        top_k=top_k,
        stop_terms=LEXORA_QUERY_STOP_TERMS,
    )
    vector_hits = []
    if query_embedding is not None and embedding_model is not None:
        vector_hits = rank_vector_documents(
            query_embedding,
            [
                EmbeddedRetrievalDocument(document=candidate, embedding=chunk.embedding)
                for chunk, candidate in zip(chunks, candidates, strict=True)
                if chunk.embedding is not None and chunk.embedding_model == embedding_model
            ],
            top_k=top_k,
        )
    hits = (
        fuse_retrieval_hits([lexical_hits, vector_hits], top_k=top_k)
        if vector_hits
        else lexical_hits
    )
    return [chunks_by_reference[hit.document.id] for hit in hits]
