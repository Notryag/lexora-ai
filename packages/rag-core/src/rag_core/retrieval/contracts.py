from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class RetrievalDocument:
    id: str
    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    document: RetrievalDocument
    score: float
    rank: int
    matched_terms: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EmbeddedRetrievalDocument:
    document: RetrievalDocument
    embedding: tuple[float, ...]
