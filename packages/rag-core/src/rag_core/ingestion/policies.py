from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChunkingPolicy:
    name: str
    version: str
    target_tokens: int = 500
    max_tokens: int = 900
    min_tokens: int = 100
    allow_cross_section: bool = False
    allow_cross_page: bool = False
    preserve_tables: bool = True
    preserve_lists: bool = True
    preserve_code: bool = True
    contextual_prefix_max_tokens: int = 120

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.version.strip():
            raise ValueError("Chunking policy name and version cannot be empty")
        if not 0 < self.min_tokens <= self.target_tokens <= self.max_tokens:
            raise ValueError("Chunk token limits must satisfy 0 < min <= target <= max")
        if self.contextual_prefix_max_tokens < 0:
            raise ValueError("contextual_prefix_max_tokens must be >= 0")
