from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class DocumentBlock:
    id: str
    content: str
    block_type: str
    heading_path: tuple[str, ...] = ()
    parent_id: str | None = None
    order: int = 0
    page_start: int | None = None
    page_end: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    file_name: str
    mime_type: str | None
    adapter: str
    adapter_version: str
    title: str | None
    blocks: tuple[DocumentBlock, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    content: str
    heading_path: tuple[str, ...]
    source_block_ids: tuple[str, ...]
    parent_block_id: str | None
    page_start: int | None
    page_end: int | None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IngestionChunk:
    content: str
    embedding_content: str
    lexical_content: str
    heading_path: tuple[str, ...]
    source_block_ids: tuple[str, ...]
    parent_block_id: str | None
    page_start: int | None
    page_end: int | None
    metadata: Mapping[str, Any] = field(default_factory=dict)
