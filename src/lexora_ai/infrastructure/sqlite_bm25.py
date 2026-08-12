from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from rag_core import RetrievalDocument

SQLITE_BM25_TOKENIZATION_VERSION = "cjk-2-3gram-v1"
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]*")
_CJK_RUN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")


@dataclass(frozen=True, slots=True)
class Bm25IndexResult:
    corpus_identity: str
    document_count: int
    total_content_chars: int
    reused: bool


@dataclass(frozen=True, slots=True)
class RankedDocumentId:
    document_id: str
    score: float
    rank: int


class SqliteBm25Index:
    def __init__(self, path: Path) -> None:
        self.path = path

    def build(
        self,
        documents: Iterable[RetrievalDocument],
        *,
        corpus_identity: str,
        max_documents: int = 60_000,
        max_content_chars: int = 20_000,
        max_total_content_chars: int = 64 * 1024 * 1024,
    ) -> Bm25IndexResult:
        if not corpus_identity.strip():
            raise ValueError("corpus_identity is required")
        if max_documents <= 0 or max_content_chars <= 0 or max_total_content_chars <= 0:
            raise ValueError("BM25 index limits must be positive")
        if self.path.exists():
            return self._existing(corpus_identity)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.part.{uuid4().hex}")
        connection = sqlite3.connect(temporary)
        document_count = 0
        total_content_chars = 0
        seen_ids: set[str] = set()
        try:
            connection.execute("PRAGMA journal_mode = OFF")
            connection.execute("PRAGMA synchronous = OFF")
            connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute(
                "CREATE VIRTUAL TABLE documents USING fts5("
                "document_id UNINDEXED, tokens, tokenize='unicode61')"
            )
            with connection:
                for document in documents:
                    if document_count >= max_documents:
                        raise ValueError("BM25 corpus exceeds max_documents")
                    document_id = document.id.strip()
                    if not document_id or document_id in seen_ids:
                        raise ValueError("BM25 document IDs must be unique and non-empty")
                    if not document.content.strip() or len(document.content) > max_content_chars:
                        raise ValueError(
                            "BM25 document content is empty or exceeds max_content_chars"
                        )
                    total_content_chars += len(document.content)
                    if total_content_chars > max_total_content_chars:
                        raise ValueError("BM25 corpus exceeds max_total_content_chars")
                    tokens = _lexical_tokens(document.content)
                    if not tokens:
                        raise ValueError("BM25 document produced no lexical tokens")
                    connection.execute(
                        "INSERT INTO documents(document_id, tokens) VALUES (?, ?)",
                        (document_id, " ".join(tokens)),
                    )
                    seen_ids.add(document_id)
                    document_count += 1
                if not document_count:
                    raise ValueError("BM25 corpus is empty")
                metadata = {
                    "corpus_identity": corpus_identity,
                    "tokenization_version": SQLITE_BM25_TOKENIZATION_VERSION,
                    "document_count": str(document_count),
                    "total_content_chars": str(total_content_chars),
                }
                connection.executemany(
                    "INSERT INTO metadata(key, value) VALUES (?, ?)",
                    metadata.items(),
                )
            connection.close()
            os.link(temporary, self.path)
            temporary.unlink()
        except Exception:
            connection.close()
            temporary.unlink(missing_ok=True)
            raise
        return Bm25IndexResult(
            corpus_identity=corpus_identity,
            document_count=document_count,
            total_content_chars=total_content_chars,
            reused=False,
        )

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        max_query_chars: int = 1_000,
        max_query_terms: int = 2_000,
    ) -> tuple[RankedDocumentId, ...]:
        if top_k <= 0 or top_k > 1_000:
            raise ValueError("top_k must be between 1 and 1000")
        if max_query_chars <= 0 or max_query_terms <= 0:
            raise ValueError("BM25 query limits must be positive")
        if len(query) > max_query_chars:
            raise ValueError("BM25 query exceeds max_query_chars")
        terms = tuple(dict.fromkeys(_lexical_tokens(query)))
        if len(terms) > max_query_terms:
            raise ValueError("BM25 query exceeds max_query_terms")
        if not terms:
            return ()
        match_query = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
        uri = f"{self.path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            rows = connection.execute(
                "SELECT document_id, bm25(documents) AS score "
                "FROM documents WHERE documents MATCH ? "
                "ORDER BY score ASC, document_id ASC LIMIT ?",
                (match_query, top_k),
            ).fetchall()
        return tuple(
            RankedDocumentId(document_id=str(document_id), score=-float(score), rank=rank)
            for rank, (document_id, score) in enumerate(rows, start=1)
        )

    def _existing(self, corpus_identity: str) -> Bm25IndexResult:
        uri = f"{self.path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            metadata = dict(connection.execute("SELECT key, value FROM metadata").fetchall())
        if metadata.get("corpus_identity") != corpus_identity:
            raise ValueError("existing BM25 index has a different corpus identity")
        if metadata.get("tokenization_version") != SQLITE_BM25_TOKENIZATION_VERSION:
            raise ValueError("existing BM25 index has a different tokenization version")
        return Bm25IndexResult(
            corpus_identity=corpus_identity,
            document_count=int(metadata["document_count"]),
            total_content_chars=int(metadata["total_content_chars"]),
            reused=True,
        )


def _lexical_tokens(text: str) -> list[str]:
    tokens = [match.group(0).lower() for match in _LATIN_TOKEN_RE.finditer(text)]
    for match in _CJK_RUN_RE.finditer(text):
        run = match.group(0).lower()
        for size in (2, 3):
            if len(run) < size:
                continue
            tokens.extend(run[index : index + size] for index in range(len(run) - size + 1))
    return tokens
