from __future__ import annotations

import re
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
    RetrievalHit,
    fuse_retrieval_hits,
    rank_lexical_documents,
    rank_vector_documents,
)

from lexora_ai.domain.legal_knowledge import LegalKnowledgeChunk

LEGAL_SOURCE_POLICY = ChunkingPolicy(
    name="lexora_legal_article_v1",
    version="lexora-legal-article-v1",
    target_tokens=500,
    max_tokens=800,
    min_tokens=20,
)
_ARTICLE_RE = re.compile(
    r"(?m)^[ \t\u3000]*(第[0-9零〇一二三四五六七八九十百千万亿两]+条"
    r"(?:之[0-9零〇一二三四五六七八九十百千万亿两]+)?)"
)
_ARTICLE_REFERENCE_RE = re.compile(
    r"第[0-9零〇一二三四五六七八九十百千万亿两]+条"
    r"(?:之[0-9零〇一二三四五六七八九十百千万亿两]+)?"
)
_DIRECT_ARTICLE_INTENT_RE = re.compile(
    r"第[0-9零〇一二三四五六七八九十百千万亿两]+条"
    r"(?:之[0-9零〇一二三四五六七八九十百千万亿两]+)?"
    r".{0,8}(?:规定|内容|全文|是什么|怎么说)"
)
_QUOTED_PHRASE_RE = re.compile(r'["“”\']([^"“”\']{2,80})["“”\']')
_LEGAL_HEADING_RE = re.compile(
    r"^[ \t\u3000]*(第[0-9零〇一二三四五六七八九十百千万亿两]+"
    r"(?P<unit>编|章|节))(?:[ \t\u3000]+.*)?$"
)
_LEGAL_HEADING_LEVELS = ("编", "章", "节")
LEGAL_KNOWLEDGE_TOP_K = 6
LEGAL_QUERY_STOP_TERMS = {"一下", "什么", "应该", "怎么", "怎样", "情况", "怎么办", "这个"}
LEGAL_QUERY_SYNONYMS = {
    "每天": "每日",
    "上限": "不超过",
    "工资": "劳动报酬",
    "拖欠工资": "未及时足额支付劳动报酬",
}
LEGAL_EXACT_QUERY_EXPANSIONS = {
    "拖欠工资": "未及时足额支付劳动报酬",
}


@dataclass(frozen=True, slots=True)
class LegalChunkDraft:
    article_label: str | None
    heading_path: tuple[str, ...]
    content: str


def split_legal_source(source_id: UUID, title: str, content: str) -> list[LegalChunkDraft]:
    sections = _legal_sections(content)

    splitter = RecursiveFallbackSplitter()
    estimator = HeuristicTokenEstimator()
    result: list[LegalChunkDraft] = []
    for section_index, (article_label, heading_path, section) in enumerate(sections, start=1):
        document = ParsedDocument(
            file_name=title,
            mime_type="text/plain",
            adapter="lexora-legal-source",
            adapter_version="v1",
            title=title,
            blocks=(
                DocumentBlock(
                    id=f"{source_id}:{section_index}",
                    content=section,
                    block_type="legal_article",
                    heading_path=(*heading_path, *((article_label,) if article_label else ())),
                ),
            ),
        )
        chunks = splitter.split(document, LEGAL_SOURCE_POLICY, estimator)
        result.extend(
            LegalChunkDraft(
                article_label=article_label,
                heading_path=heading_path,
                content=chunk.content,
            )
            for chunk in chunks
        )
    return result


def _legal_sections(content: str) -> list[tuple[str | None, tuple[str, ...], str]]:
    hierarchy: dict[str, str] = {}
    sections: list[tuple[str | None, tuple[str, ...], str]] = []
    article_label: str | None = None
    article_path: tuple[str, ...] = ()
    article_lines: list[str] = []

    def flush_article() -> None:
        nonlocal article_label, article_path, article_lines
        if article_label is not None and article_lines:
            sections.append((article_label, article_path, "\n".join(article_lines).strip()))
        article_label = None
        article_path = ()
        article_lines = []

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading = _LEGAL_HEADING_RE.match(line)
        if heading:
            flush_article()
            unit = heading.group("unit")
            hierarchy[unit] = line
            level = _LEGAL_HEADING_LEVELS.index(unit)
            for lower_level in _LEGAL_HEADING_LEVELS[level + 1 :]:
                hierarchy.pop(lower_level, None)
            continue
        article = _ARTICLE_RE.match(line)
        if article:
            flush_article()
            article_label = article.group(1)
            article_path = tuple(
                hierarchy[level]
                for level in _LEGAL_HEADING_LEVELS
                if level in hierarchy
            )
            article_lines = [line]
            continue
        if article_label is not None:
            article_lines.append(line)

    flush_article()
    return sections or [(None, (), content.strip())]


def rank_legal_knowledge(
    query: str,
    chunks: list[LegalKnowledgeChunk],
    *,
    query_embedding: tuple[float, ...] | None,
    embedding_model: str | None,
    top_k: int = LEGAL_KNOWLEDGE_TOP_K,
) -> list[LegalKnowledgeChunk]:
    candidate_k = max(top_k * 3, top_k)
    retrieval_query = _expand_legal_query(query)
    chunks_by_reference = {chunk.reference: chunk for chunk in chunks}
    documents = [
        RetrievalDocument(
            id=chunk.reference,
            content=" ".join(
                part
                for part in (
                    chunk.title,
                    *chunk.heading_path,
                    chunk.article_label,
                    chunk.content,
                )
                if part
            ),
        )
        for chunk in chunks
    ]
    exact_hits = _rank_exact_legal_documents(
        query,
        documents,
        chunks,
        top_k=candidate_k,
    )
    lexical_hits = rank_lexical_documents(
        retrieval_query,
        documents,
        top_k=candidate_k,
        stop_terms=LEGAL_QUERY_STOP_TERMS,
    )
    vector_hits = []
    if query_embedding is not None and embedding_model is not None:
        vector_hits = rank_vector_documents(
            query_embedding,
            [
                EmbeddedRetrievalDocument(document=document, embedding=tuple(chunk.embedding))
                for chunk, document in zip(chunks, documents, strict=True)
                if chunk.embedding is not None and chunk.embedding_model == embedding_model
            ],
            top_k=candidate_k,
        )
    rankings = [ranking for ranking in (exact_hits, lexical_hits, vector_hits) if ranking]
    if not rankings:
        return []
    hits = fuse_retrieval_hits(rankings, top_k=top_k) if len(rankings) > 1 else rankings[0][:top_k]
    hits = _promote_direct_article_hits(query, exact_hits, hits, chunks_by_reference, top_k)
    return [chunks_by_reference[hit.document.id] for hit in hits]


def _rank_exact_legal_documents(
    query: str,
    documents: list[RetrievalDocument],
    chunks: list[LegalKnowledgeChunk],
    *,
    top_k: int,
) -> list[RetrievalHit]:
    article_references = tuple(dict.fromkeys(_ARTICLE_REFERENCE_RE.findall(query)))
    quoted_phrases = tuple(dict.fromkeys(_QUOTED_PHRASE_RE.findall(query)))
    canonical_phrases = tuple(
        replacement
        for term, replacement in LEGAL_EXACT_QUERY_EXPANSIONS.items()
        if term in query
    )
    if not article_references and not quoted_phrases and not canonical_phrases:
        return []

    scored: list[tuple[float, int, RetrievalDocument, tuple[str, ...]]] = []
    for source_order, (document, chunk) in enumerate(zip(documents, chunks, strict=True)):
        matched_terms = tuple(
            term
            for term in (*article_references, *quoted_phrases, *canonical_phrases)
            if term == chunk.article_label or term in chunk.content
        )
        if not matched_terms:
            continue
        score = float(sum(5 if term == chunk.article_label else 2 for term in matched_terms))
        if _law_title_matches_query(chunk.title, query):
            score += 3
        scored.append((score, source_order, document, matched_terms))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        RetrievalHit(
            document=document,
            score=score,
            rank=rank,
            matched_terms=matched_terms,
        )
        for rank, (score, _, document, matched_terms) in enumerate(scored[:top_k], start=1)
    ]


def _law_title_matches_query(title: str, query: str) -> bool:
    short_title = title.removeprefix("中华人民共和国")
    return title in query or (short_title != title and short_title in query)


def _promote_direct_article_hits(
    query: str,
    exact_hits: list[RetrievalHit],
    fused_hits: list[RetrievalHit],
    chunks_by_reference: dict[str, LegalKnowledgeChunk],
    top_k: int,
) -> list[RetrievalHit]:
    if not _DIRECT_ARTICLE_INTENT_RE.search(query):
        return fused_hits
    article_references = set(_ARTICLE_REFERENCE_RE.findall(query))
    if not article_references:
        return fused_hits
    direct_hits = [
        hit
        for hit in exact_hits
        if chunks_by_reference[hit.document.id].article_label in article_references
        and _law_title_matches_query(chunks_by_reference[hit.document.id].title, query)
    ]
    if not direct_hits:
        return fused_hits
    direct_ids = {hit.document.id for hit in direct_hits}
    return [*direct_hits, *(hit for hit in fused_hits if hit.document.id not in direct_ids)][:top_k]


def _expand_legal_query(query: str) -> str:
    expansions = [replacement for term, replacement in LEGAL_QUERY_SYNONYMS.items() if term in query]
    return " ".join((query, *expansions))
