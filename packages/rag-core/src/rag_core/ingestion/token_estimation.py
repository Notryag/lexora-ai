from __future__ import annotations

import re
from typing import Protocol

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[._+/-][A-Za-z0-9]+)*")


class TokenEstimator(Protocol):
    version: str

    def estimate(self, text: str) -> int: ...


class SlicingTokenEstimator(TokenEstimator, Protocol):
    def prefix_within(self, text: str, max_tokens: int) -> str: ...

    def suffix_within(self, text: str, max_tokens: int) -> str: ...


class HeuristicTokenEstimator:
    version = "unicode-heuristic-v1"

    def estimate(self, text: str) -> int:
        cjk_count = len(_CJK_RE.findall(text))
        latin_count = len(_LATIN_TOKEN_RE.findall(text))
        remaining = max(len(text) - cjk_count, 0)
        punctuation_estimate = remaining // 8
        return max(cjk_count + latin_count + punctuation_estimate, 1) if text else 0

    def prefix_within(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if self.estimate(text) <= max_tokens:
            return text
        low, high = 1, len(text)
        while low < high:
            midpoint = (low + high + 1) // 2
            if self.estimate(text[:midpoint]) <= max_tokens:
                low = midpoint
            else:
                high = midpoint - 1
        return text[:low]

    def suffix_within(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if self.estimate(text) <= max_tokens:
            return text
        low, high = 1, len(text)
        while low < high:
            midpoint = (low + high + 1) // 2
            if self.estimate(text[-midpoint:]) <= max_tokens:
                low = midpoint
            else:
                high = midpoint - 1
        return text[-low:]
