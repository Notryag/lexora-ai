from __future__ import annotations

import pytest

from rag_core import (
    ChunkingPolicy,
    DocumentBlock,
    HeuristicTokenEstimator,
    HierarchicalSplitter,
    ParsedDocument,
    RecursiveFallbackSplitter,
    SplitterRegistry,
    default_splitter_registry,
)


def build_document(*blocks: DocumentBlock) -> ParsedDocument:
    return ParsedDocument(
        file_name="document.txt",
        mime_type="text/plain",
        adapter="test",
        adapter_version="v1",
        title=None,
        blocks=blocks,
    )


def test_policy_rejects_invalid_token_limits() -> None:
    with pytest.raises(ValueError, match="min <= target <= max"):
        ChunkingPolicy(name="invalid", version="v1", min_tokens=10, target_tokens=5)


def test_recursive_splitter_preserves_source_provenance() -> None:
    document = build_document(
        DocumentBlock(
            id="block-1",
            content="第一句。第二句。第三句。第四句。",
            block_type="paragraph",
            heading_path=("章节",),
            page_start=2,
            page_end=2,
        )
    )
    policy = ChunkingPolicy(
        name="small",
        version="v1",
        min_tokens=2,
        target_tokens=5,
        max_tokens=7,
    )

    chunks = RecursiveFallbackSplitter().split(
        document,
        policy,
        HeuristicTokenEstimator(),
    )

    assert len(chunks) > 1
    assert all(chunk.source_block_ids == ("block-1",) for chunk in chunks)
    assert all(chunk.page_start == 2 for chunk in chunks)
    assert chunks[1].metadata["is_continuation"] is True


def test_hierarchical_splitter_does_not_merge_sections_by_default() -> None:
    document = build_document(
        DocumentBlock("a", "第一部分。", "paragraph", heading_path=("A",), order=1),
        DocumentBlock("b", "第二部分。", "paragraph", heading_path=("B",), order=2),
    )
    policy = ChunkingPolicy(
        name="sections",
        version="v1",
        min_tokens=1,
        target_tokens=100,
        max_tokens=120,
    )

    chunks = HierarchicalSplitter().split(document, policy, HeuristicTokenEstimator())

    assert [chunk.source_block_ids for chunk in chunks] == [("a",), ("b",)]


def test_registry_rejects_duplicate_splitter_names() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        SplitterRegistry([RecursiveFallbackSplitter(), RecursiveFallbackSplitter()])


def test_default_registry_exposes_stable_splitters() -> None:
    assert default_splitter_registry().names == frozenset({"hierarchical", "recursive"})
