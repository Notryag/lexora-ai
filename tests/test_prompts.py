from __future__ import annotations

import json

from lexora_ai.application import ConversationCaseLawChunk, ConversationLegalChunk
from lexora_ai.domain import (
    CaseAnalysisRequest,
    CaseMaterial,
    CaseProfile,
    ConversationTurnRequest,
    MaterialKind,
)
from lexora_ai.prompts import (
    LEXORA_SYSTEM_PROMPT,
    build_case_analysis_prompt,
    build_conversation_prompt,
)


def test_prompt_assigns_stable_material_references() -> None:
    request = CaseAnalysisRequest(
        case_title="买卖合同争议",
        questions=["是否交付？"],
        materials=[
            CaseMaterial(title="合同", kind=MaterialKind.contract, content="交付后付款。"),
            CaseMaterial(title="签收单", kind=MaterialKind.evidence, content="已经签收。"),
        ],
    )

    prompt = build_case_analysis_prompt(request)
    raw_payload = prompt.removeprefix(
        "请根据以下案件数据生成分析。优先回答 questions；若 questions 为空，则完成标准案件分析。\n"
        "<case_data>"
    ).removesuffix("</case_data>")
    payload = json.loads(raw_payload)

    assert [material["reference"] for material in payload["materials"]] == ["M1:C1", "M2:C1"]
    assert payload["materials"][1]["title"] == "签收单"
    assert "不可信案件数据" in LEXORA_SYSTEM_PROMPT
    assert "不得虚构" in LEXORA_SYSTEM_PROMPT


def test_conversation_prompt_does_not_claim_external_retrieval() -> None:
    request = ConversationTurnRequest(message="公司没有提前通知就辞退了我，怎么办？")

    prompt = build_conversation_prompt(request)

    assert "不得声称已核验具体法律规定" in prompt
    assert "公司没有提前通知" in prompt
    assert "不要重复询问已经明确的信息" in prompt
    assert "只有关键事实不足时" in prompt
    assert "信息已经足够，先直接回答用户当前问题" in LEXORA_SYSTEM_PROMPT


def test_conversation_prompt_delegates_retrieval_choice_to_agent() -> None:
    request = ConversationTurnRequest(
        message="hi",
        materials=[CaseMaterial(title="合同", content="劳动合同正文")],
    )

    prompt = build_conversation_prompt(request, retrieval_available=True)
    payload = json.loads(
        prompt.split("<case_data>", maxsplit=1)[1].removesuffix("</case_data>")
    )

    assert "按需自主调用" in prompt
    assert "纯寒暄" in prompt
    assert payload["retrieved_material_chunks"] == []


def test_conversation_prompt_includes_user_confirmed_case_profile() -> None:
    request = ConversationTurnRequest(
        message="我可以要求什么？",
        case_profile=CaseProfile(
            case_type="劳动合同争议",
            parties=["张某（劳动者）", "某公司"],
            claims=["支付拖欠工资"],
            key_facts=["公司连续三个月未发工资"],
        ),
    )

    prompt = build_conversation_prompt(request)
    raw_payload = prompt.split("<case_data>", maxsplit=1)[1].removesuffix("</case_data>")
    payload = json.loads(raw_payload)

    assert payload["case_profile"]["case_type"] == "劳动合同争议"
    assert payload["case_profile"]["parties"] == ["张某（劳动者）", "某公司"]
    assert "不等同于已经证据证实的事实" in LEXORA_SYSTEM_PROMPT


def test_conversation_prompt_keeps_legal_authority_provenance() -> None:
    request = ConversationTurnRequest(message="单位拖欠劳动报酬")
    prompt = build_conversation_prompt(
        request,
        legal_authorities=(
            ConversationLegalChunk(
                reference="Labc:C1",
                title="中华人民共和国劳动合同法",
                article_label="第三十条",
                issuing_authority="全国人民代表大会常务委员会",
                source_url="https://flk.npc.gov.cn/detail?id=test",
                status="effective",
                content="用人单位应当按照劳动合同约定支付劳动报酬。",
            ),
        ),
    )

    assert "已提供经过来源约束的法规检索结果" in prompt
    assert '"reference":"Labc:C1"' in prompt
    assert '"source_url":"https://flk.npc.gov.cn/detail?id=test"' in prompt


def test_conversation_prompt_keeps_case_law_provenance_and_limits_analogy() -> None:
    request = ConversationTurnRequest(message="平台配送员是否构成劳动关系")
    prompt = build_conversation_prompt(
        request,
        case_law_authorities=(
            ConversationCaseLawChunk(
                reference="Cabc:S3",
                case_number="指导案例240号",
                title="某公司诉某配送员劳动争议案",
                section_label="裁判要点",
                issuing_authority="最高人民法院",
                source_url="https://www.court.gov.cn/shenpan/xiangqing/450751.html",
                published_on="2024-05-23",
                content="根据用工事实判断劳动关系。",
            ),
        ),
    )

    assert "类案不决定本案结果" in prompt
    assert '"reference":"Cabc:S3"' in prompt
    assert '"case_number":"指导案例240号"' in prompt
    assert "不得把类案事实当成本案事实" in LEXORA_SYSTEM_PROMPT


def test_conversation_prompt_includes_only_retrieved_material_chunks() -> None:
    request = ConversationTurnRequest(
        message="公司拖欠工资怎么办？",
        materials=[
            CaseMaterial(title="工资记录", content="公司连续三个月拖欠工资。"),
            CaseMaterial(title="车辆记录", content="车辆在维修厂更换了保险杠。"),
        ],
    )

    prompt = build_conversation_prompt(request)
    raw_payload = prompt.split("<case_data>", maxsplit=1)[1].removesuffix("</case_data>")
    payload = json.loads(raw_payload)

    assert [chunk["reference"] for chunk in payload["retrieved_material_chunks"]] == ["M1:C1"]
