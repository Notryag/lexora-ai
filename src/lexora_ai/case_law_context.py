from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from rag_core import (
    ChunkingPolicy,
    DocumentBlock,
    EmbeddedRetrievalDocument,
    HeuristicTokenEstimator,
    ParsedDocument,
    RecursiveFallbackSplitter,
    RetrievalDocument,
    fuse_retrieval_hits,
    query_terms,
    rank_lexical_documents,
    rank_vector_documents,
)

from lexora_ai.domain import CaseLawChunk

CASE_LAW_POLICY = ChunkingPolicy(
    name="lexora_case_law_section_v1",
    version="lexora-case-law-section-v1",
    target_tokens=500,
    max_tokens=800,
    min_tokens=20,
)
CASE_LAW_SECTIONS = (
    "案例信息",
    "关键词",
    "裁判要点",
    "裁判要旨",
    "相关法条",
    "基本案情",
    "裁判结果",
    "裁判理由",
    "典型意义",
    "关联索引",
)
CASE_LAW_TOP_K = 5
CASE_LAW_MAX_CHUNKS_PER_SOURCE = 2
CASE_LAW_MIN_LEXICAL_SCORE = 3.0
CASE_LAW_MIN_VECTOR_SCORE = 0.55
CASE_LAW_STOP_TERMS = {
    "一下",
    "可以",
    "是否",
    "能否",
    "什么",
    "应该",
    "怎么",
    "怎样",
    "情况",
    "怎么办",
    "这个",
    "案件",
}


@dataclass(frozen=True, slots=True)
class CaseLawChunkDraft:
    section_label: str
    content: str


def split_case_law(source_id: UUID, title: str, content: str) -> list[CaseLawChunkDraft]:
    sections = _sections(content)
    splitter = RecursiveFallbackSplitter()
    estimator = HeuristicTokenEstimator()
    result: list[CaseLawChunkDraft] = []
    for section_index, (section_label, section) in enumerate(sections, start=1):
        parsed = ParsedDocument(
            file_name=title,
            mime_type="text/plain",
            adapter="lexora-case-law-source",
            adapter_version="v1",
            title=title,
            blocks=(
                DocumentBlock(
                    id=f"{source_id}:{section_index}",
                    content=section,
                    block_type="case_law_section",
                    heading_path=(section_label,),
                ),
            ),
        )
        chunks = splitter.split(parsed, CASE_LAW_POLICY, estimator)
        result.extend(
            CaseLawChunkDraft(section_label=section_label, content=chunk.content)
            for chunk in chunks
        )
    return result


def _sections(content: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    current_label = "案例信息"
    current_lines: list[str] = []

    def flush() -> None:
        if current_lines:
            result.append((current_label, "\n".join(current_lines).strip()))

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line in CASE_LAW_SECTIONS:
            flush()
            current_label = line
            current_lines = []
            continue
        current_lines.append(line)
    flush()
    return result or [("案例信息", content.strip())]


def rank_case_law(
    query: str,
    chunks: list[CaseLawChunk],
    *,
    query_embedding: tuple[float, ...] | None,
    embedding_model: str | None,
    top_k: int = CASE_LAW_TOP_K,
) -> list[CaseLawChunk]:
    if not query.strip() or not chunks or top_k <= 0:
        return []
    candidate_k = max(top_k * 3, top_k)
    by_reference = {chunk.reference: chunk for chunk in chunks}
    documents = [
        RetrievalDocument(
            id=chunk.reference,
            content=" ".join(
                (
                    chunk.case_number,
                    chunk.title,
                    *chunk.keywords,
                    chunk.section_label,
                    chunk.content,
                )
            ),
        )
        for chunk in chunks
    ]
    lexical_terms = query_terms(query, stop_terms=CASE_LAW_STOP_TERMS)
    minimum_lexical_score = (
        1.0 if len(lexical_terms) <= 2 else CASE_LAW_MIN_LEXICAL_SCORE
    )
    lexical_hits = [
        hit
        for hit in rank_lexical_documents(
            query,
            documents,
            top_k=candidate_k,
            stop_terms=CASE_LAW_STOP_TERMS,
        )
        if hit.score >= minimum_lexical_score
    ]
    vector_hits = []
    if query_embedding is not None and embedding_model is not None:
        vector_hits = [
            hit
            for hit in rank_vector_documents(
                query_embedding,
                [
                    EmbeddedRetrievalDocument(
                        document=document, embedding=tuple(chunk.embedding)
                    )
                    for chunk, document in zip(chunks, documents, strict=True)
                    if chunk.embedding is not None
                    and chunk.embedding_model == embedding_model
                ],
                top_k=candidate_k,
            )
            if hit.score >= CASE_LAW_MIN_VECTOR_SCORE
        ]
    rankings = [ranking for ranking in (lexical_hits, vector_hits) if ranking]
    if not rankings:
        return []
    ranked_hits = (
        fuse_retrieval_hits(rankings, top_k=candidate_k)
        if len(rankings) > 1
        else rankings[0][:candidate_k]
    )
    result: list[CaseLawChunk] = []
    source_counts: dict[UUID, int] = {}
    for hit in ranked_hits:
        chunk = by_reference[hit.document.id]
        source_count = source_counts.get(chunk.source_id, 0)
        if source_count >= CASE_LAW_MAX_CHUNKS_PER_SOURCE:
            continue
        result.append(chunk)
        source_counts[chunk.source_id] = source_count + 1
        if len(result) == top_k:
            break
    return result
