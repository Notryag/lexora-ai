from __future__ import annotations

import pytest

from lexora_ai.infrastructure.north_tools import build_legal_retrieval_tools


class RecordingRetrieval:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def search_materials(self, query: str):
        self.calls.append(("materials", query))
        return ()

    async def search_legal_authorities(self, query: str):
        self.calls.append(("legal", query))
        return ()

    async def search_case_law(self, query: str):
        self.calls.append(("cases", query))
        return ()


@pytest.mark.asyncio
async def test_agent_retrieval_tools_keep_sources_separate() -> None:
    retrieval = RecordingRetrieval()
    tools = {tool.name: tool for tool in build_legal_retrieval_tools(retrieval)}

    assert set(tools) == {
        "search_case_materials",
        "search_legal_authorities",
        "search_guiding_cases",
    }

    result = await tools["search_legal_authorities"].ainvoke(
        {"query": "解除劳动合同的补偿规则"}
    )

    assert result == {"legal_authorities": []}
    assert retrieval.calls == [("legal", "解除劳动合同的补偿规则")]
