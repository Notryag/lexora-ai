from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from rag_core.ingestion.contracts import ChunkDraft, DocumentBlock, ParsedDocument
from rag_core.ingestion.policies import ChunkingPolicy
from rag_core.ingestion.token_estimation import SlicingTokenEstimator, TokenEstimator

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？!?；;.!])\s*")


class DocumentSplitter(Protocol):
    name: str
    version: str

    def split(
        self,
        document: ParsedDocument,
        policy: ChunkingPolicy,
        estimator: SlicingTokenEstimator,
    ) -> list[ChunkDraft]: ...


def split_text_to_limit(
    text: str,
    *,
    target_tokens: int,
    max_tokens: int,
    estimator: SlicingTokenEstimator,
) -> list[str]:
    if not 0 < target_tokens <= max_tokens:
        raise ValueError("text split limits must satisfy 0 < target <= max")
    if estimator.estimate(text) <= max_tokens:
        return [text.strip()] if text.strip() else []
    sentences = [
        sentence.strip() for sentence in _SENTENCE_BOUNDARY_RE.split(text) if sentence.strip()
    ]
    parts: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        if estimator.estimate(sentence) > max_tokens:
            if current:
                parts.append("".join(current))
                current = []
            parts.extend(_hard_split(sentence, max_tokens=max_tokens, estimator=estimator))
            continue
        candidate = "".join([*current, sentence])
        if current and estimator.estimate(candidate) > target_tokens:
            parts.append("".join(current))
            current = [sentence]
        else:
            current.append(sentence)
    if current:
        parts.append("".join(current))
    return [part for part in parts if part]


def _hard_split(
    text: str,
    *,
    max_tokens: int,
    estimator: SlicingTokenEstimator,
) -> list[str]:
    parts: list[str] = []
    remaining = text
    while remaining:
        candidate = estimator.prefix_within(remaining, max_tokens)
        part = candidate.strip()
        if not candidate or not part:
            break
        parts.append(part)
        remaining = remaining[len(candidate) :].lstrip()
    return parts


class RecursiveFallbackSplitter:
    name = "recursive"
    version = "recursive-fallback-v1"

    def split(
        self,
        document: ParsedDocument,
        policy: ChunkingPolicy,
        estimator: SlicingTokenEstimator,
    ) -> list[ChunkDraft]:
        chunks: list[ChunkDraft] = []
        for block in document.blocks:
            parts = split_text_to_limit(
                block.content,
                target_tokens=policy.target_tokens,
                max_tokens=policy.max_tokens,
                estimator=estimator,
            )
            for part_index, part in enumerate(parts):
                chunks.append(
                    ChunkDraft(
                        content=part,
                        heading_path=block.heading_path,
                        source_block_ids=(block.id,),
                        parent_block_id=block.parent_id or block.id,
                        page_start=block.page_start,
                        page_end=block.page_end,
                        metadata={
                            "block_types": [block.block_type],
                            "chunk_in_block": part_index,
                            "is_continuation": part_index > 0
                            or bool(block.metadata.get("is_continuation")),
                            "cross_page_continuation": bool(
                                block.metadata.get("cross_page_continuation")
                            ),
                            "splitter": self.name,
                            "splitter_version": self.version,
                            "policy": policy.name,
                            "policy_version": policy.version,
                            "token_estimator_version": estimator.version,
                            "estimated_tokens": estimator.estimate(part),
                        },
                    )
                )
        return chunks


@dataclass(slots=True)
class _DraftGroup:
    blocks: list[DocumentBlock]


class HierarchicalSplitter:
    name = "hierarchical"
    version = "hierarchical-v1"

    def split(
        self,
        document: ParsedDocument,
        policy: ChunkingPolicy,
        estimator: SlicingTokenEstimator,
    ) -> list[ChunkDraft]:
        expanded = self._expand_oversized_blocks(document.blocks, policy, estimator)
        groups: list[_DraftGroup] = []
        current = _DraftGroup(blocks=[])
        for block in expanded:
            if not current.blocks:
                current.blocks.append(block)
                continue
            if self._can_merge(current.blocks, block, policy, estimator):
                current.blocks.append(block)
            else:
                groups.append(current)
                current = _DraftGroup(blocks=[block])
        if current.blocks:
            groups.append(current)
        self._merge_small_tail(groups, policy, estimator)
        return [self._to_chunk(group.blocks, policy, estimator) for group in groups]

    def _expand_oversized_blocks(
        self,
        blocks: tuple[DocumentBlock, ...],
        policy: ChunkingPolicy,
        estimator: SlicingTokenEstimator,
    ) -> list[DocumentBlock]:
        expanded: list[DocumentBlock] = []
        for block in blocks:
            atomic = _is_preserved_atomic(block, policy)
            if atomic or estimator.estimate(block.content) <= policy.max_tokens:
                expanded.append(block)
                continue
            parts = split_text_to_limit(
                block.content,
                target_tokens=policy.target_tokens,
                max_tokens=policy.max_tokens,
                estimator=estimator,
            )
            for part_index, part in enumerate(parts):
                expanded.append(
                    DocumentBlock(
                        id=f"{block.id}-part-{part_index}",
                        content=part,
                        block_type=block.block_type,
                        heading_path=block.heading_path,
                        parent_id=block.id,
                        order=block.order,
                        page_start=block.page_start,
                        page_end=block.page_end,
                        metadata={
                            **dict(block.metadata),
                            "split_part_index": part_index,
                            "split_part_count": len(parts),
                            "is_continuation": part_index > 0,
                        },
                    )
                )
        return expanded

    def _can_merge(
        self,
        current: list[DocumentBlock],
        candidate: DocumentBlock,
        policy: ChunkingPolicy,
        estimator: TokenEstimator,
    ) -> bool:
        previous = current[-1]
        if not policy.allow_cross_section and previous.heading_path != candidate.heading_path:
            return False
        if not policy.allow_cross_page and _crosses_page(previous, candidate):
            return False
        if _is_preserved_atomic(candidate, policy) or _is_preserved_atomic(previous, policy):
            return False
        related = (
            previous.parent_id == candidate.parent_id
            or candidate.parent_id == previous.id
            or previous.parent_id == candidate.id
            or (previous.parent_id is None and candidate.parent_id is None)
        )
        if not related:
            return False
        candidate_text = "\n\n".join([*(block.content for block in current), candidate.content])
        return estimator.estimate(candidate_text) <= policy.target_tokens

    def _merge_small_tail(
        self,
        groups: list[_DraftGroup],
        policy: ChunkingPolicy,
        estimator: TokenEstimator,
    ) -> None:
        if len(groups) < 2:
            return
        tail = groups[-1]
        previous = groups[-2]
        if estimator.estimate(_group_content(tail.blocks)) >= policy.min_tokens:
            return
        if not self._can_merge(previous.blocks, tail.blocks[0], policy, estimator):
            return
        combined = [*previous.blocks, *tail.blocks]
        if estimator.estimate(_group_content(combined)) <= policy.max_tokens:
            previous.blocks.extend(tail.blocks)
            groups.pop()

    def _to_chunk(
        self,
        blocks: list[DocumentBlock],
        policy: ChunkingPolicy,
        estimator: TokenEstimator,
    ) -> ChunkDraft:
        pages = [
            page
            for block in blocks
            for page in (block.page_start, block.page_end)
            if page is not None
        ]
        content = _group_content(blocks)
        return ChunkDraft(
            content=content,
            heading_path=blocks[-1].heading_path,
            source_block_ids=tuple(block.id for block in blocks),
            parent_block_id=blocks[-1].parent_id or blocks[-1].id,
            page_start=min(pages) if pages else None,
            page_end=max(pages) if pages else None,
            metadata={
                "block_types": list(dict.fromkeys(block.block_type for block in blocks)),
                "is_continuation": bool(blocks[0].metadata.get("is_continuation")),
                "cross_page_continuation": bool(
                    blocks[0].metadata.get("cross_page_continuation")
                ),
                "splitter": self.name,
                "splitter_version": self.version,
                "policy": policy.name,
                "policy_version": policy.version,
                "token_estimator_version": estimator.version,
                "estimated_tokens": estimator.estimate(content),
                "atomic_oversized": any(
                    _is_preserved_atomic(block, policy)
                    and estimator.estimate(block.content) > policy.max_tokens
                    for block in blocks
                ),
            },
        )


def _group_content(blocks: list[DocumentBlock]) -> str:
    return "\n\n".join(block.content for block in blocks)


def _crosses_page(previous: DocumentBlock, current: DocumentBlock) -> bool:
    return (
        previous.page_end is not None
        and current.page_start is not None
        and previous.page_end != current.page_start
    )


def _is_preserved_atomic(block: DocumentBlock, policy: ChunkingPolicy) -> bool:
    return (
        (block.block_type == "table" and policy.preserve_tables)
        or (block.block_type == "code" and policy.preserve_code)
        or (block.block_type == "list_item" and policy.preserve_lists)
    )
