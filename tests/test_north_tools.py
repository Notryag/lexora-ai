from __future__ import annotations

import pytest

from lexora_ai.domain import CaseProfile
from lexora_ai.infrastructure.north_tools import build_lexora_tools


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


class RecordingCaseMemory:
    def __init__(self) -> None:
        self.profile = CaseProfile(missing_information=["房屋购买时间"])
        self.patches = []

    async def update_profile(self, patch):
        self.patches.append(patch)
        self.profile = patch.apply(self.profile)
        return self.profile

@pytest.mark.asyncio
async def test_agent_retrieval_tools_keep_sources_separate() -> None:
    retrieval = RecordingRetrieval()
    tools = {tool.name: tool for tool in build_lexora_tools(retrieval, None)}

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


@pytest.mark.asyncio
async def test_agent_case_memory_tool_stages_only_structured_profile_changes() -> None:
    memory = RecordingCaseMemory()
    tools = {tool.name: tool for tool in build_lexora_tools(None, memory)}

    assert set(tools) == {"update_case_profile"}

    result = await tools["update_case_profile"].ainvoke(
        {
            "case_type": "离婚财产分割",
            "parties": ["用户（妻子）", "配偶（丈夫）"],
            "key_facts": ["房屋在婚后购买", "房屋登记在双方名下"],
            "resolved_missing_information": ["房屋购买时间"],
        }
    )

    assert result["case_profile"]["case_type"] == "离婚财产分割"
    assert result["case_profile"]["missing_information"] == []
    assert memory.patches[0].key_facts == ["房屋在婚后购买", "房屋登记在双方名下"]

    cleared = await tools["update_case_profile"].ainvoke({"missing_information": []})
    assert cleared["case_profile"]["missing_information"] == []
