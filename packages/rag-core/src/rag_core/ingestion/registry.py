from __future__ import annotations

from functools import lru_cache

from rag_core.ingestion.splitting import (
    DocumentSplitter,
    HierarchicalSplitter,
    RecursiveFallbackSplitter,
)


class SplitterRegistry:
    def __init__(self, splitters: list[DocumentSplitter]) -> None:
        self._splitters = {splitter.name: splitter for splitter in splitters}
        if len(self._splitters) != len(splitters):
            raise ValueError("Duplicate ingestion splitter name")

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._splitters)

    def get(self, name: str) -> DocumentSplitter:
        try:
            return self._splitters[name]
        except KeyError as exc:
            raise ValueError(f"Unknown ingestion splitter: {name}") from exc


@lru_cache(maxsize=1)
def default_splitter_registry() -> SplitterRegistry:
    return SplitterRegistry([HierarchicalSplitter(), RecursiveFallbackSplitter()])
