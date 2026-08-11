from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from agent_platform.application import AgentRunService
from agent_platform.core import UserContext
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from lexora_ai.application import (
    CaseLawSourceService,
    CaseRunService,
    CaseWorkspaceService,
    ConversationCaseLawChunk,
    ConversationContextMessage,
    ConversationEvidenceChunk,
    ConversationLegalChunk,
    GeneratedConversationTurn,
    LegalSourceService,
    PersistentLegalConversationService,
)
from lexora_ai.application.persistent_conversation import (
    _strip_unavailable_authority_references,
)
from lexora_ai.db.models import Base
from lexora_ai.db.unit_of_work import LexoraUnitOfWork
from lexora_ai.domain import (
    CaseConversationTurnRequest,
    CaseLawSourceCreate,
    CaseMaterial,
    CaseProfile,
    CaseProfilePatch,
    CaseProfileUpdate,
    ConversationTurnRequest,
    LegalCaseCreate,
    LegalSourceCreate,
    LegalSourceKind,
    LegalSourceReviewStatus,
    LegalSourceStatus,
    LegalSourceUpdate,
)
from lexora_ai.domain.cases import MAX_MATERIAL_CHARS
from lexora_ai.infrastructure import DatabaseCaseLawKnowledgePort, DatabaseLegalKnowledgePort
from lexora_ai.infrastructure.material_parser import MaterialParseError, parse_material_file


def test_unavailable_authority_references_are_removed_from_model_output() -> None:
    content = "规则一[Lknown:C1]，错误引用[Lunknown:C9]，材料引用[M1:C1]。"

    assert _strip_unavailable_authority_references(content, {"Lknown:C1"}) == (
        "规则一[Lknown:C1]，错误引用，材料引用[M1:C1]。"
    )


class RecordingGateway:
    def __init__(self) -> None:
        self.histories: list[tuple[ConversationContextMessage, ...]] = []
        self.evidence: list[tuple[ConversationEvidenceChunk, ...]] = []
        self.legal_authorities: list[tuple[ConversationLegalChunk, ...]] = []
        self.case_law_authorities: list[tuple[ConversationCaseLawChunk, ...]] = []
        self.requests: list[ConversationTurnRequest] = []

    async def converse(
        self,
        request: ConversationTurnRequest,
        *,
        thread_id,
        run_id=None,
        checkpoint_id=None,
        history: tuple[ConversationContextMessage, ...] = (),
        evidence: tuple[ConversationEvidenceChunk, ...] | None = None,
        legal_authorities: tuple[ConversationLegalChunk, ...] = (),
        case_law_authorities: tuple[ConversationCaseLawChunk, ...] = (),
        retrieval=None,
        case_memory=None,
    ) -> GeneratedConversationTurn:
        del run_id, checkpoint_id
        if retrieval is not None:
            evidence = await retrieval.search_materials(request.message)
            legal_authorities = await retrieval.search_legal_authorities(request.message)
            case_law_authorities = await retrieval.search_case_law(request.message)
        assert evidence is not None
        self.requests.append(request)
        self.histories.append(history)
        self.evidence.append(evidence)
        self.legal_authorities.append(legal_authorities)
        self.case_law_authorities.append(case_law_authorities)
        cited_authorities = [
            chunks[0].reference
            for chunks in (legal_authorities, case_law_authorities)
            if chunks
        ]
        citations = "".join(f" [{reference}]" for reference in cited_authorities)
        return GeneratedConversationTurn(
            content=f"已记录：{request.message} [M1:C1]{citations}",
            runtime_thread_id=str(thread_id),
        )

    async def converse_stream(
        self,
        request: ConversationTurnRequest,
        *,
        thread_id,
        run_id=None,
        checkpoint_id=None,
        on_text_delta,
        history: tuple[ConversationContextMessage, ...] = (),
        evidence: tuple[ConversationEvidenceChunk, ...] | None = None,
        legal_authorities: tuple[ConversationLegalChunk, ...] = (),
        case_law_authorities: tuple[ConversationCaseLawChunk, ...] = (),
        retrieval=None,
        case_memory=None,
    ) -> GeneratedConversationTurn:
        result = await self.converse(
            request,
            thread_id=thread_id,
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            history=history,
            evidence=evidence,
            legal_authorities=legal_authorities,
            case_law_authorities=case_law_authorities,
            retrieval=retrieval,
            case_memory=case_memory,
        )
        on_text_delta("已记录：")
        on_text_delta(f"{request.message} [M1:C1]")
        return result


class CheckpointRecordingGateway:
    def __init__(self) -> None:
        self.thread_ids = []
        self.run_ids = []
        self.checkpoint_ids = []
        self.histories = []

    async def converse(
        self,
        request,
        *,
        thread_id,
        run_id,
        checkpoint_id,
        history=(),
        **kwargs,
    ):
        del request, kwargs
        self.thread_ids.append(thread_id)
        self.run_ids.append(run_id)
        self.checkpoint_ids.append(checkpoint_id)
        self.histories.append(history)
        next_checkpoint_id = f"checkpoint-{len(self.run_ids)}"
        return GeneratedConversationTurn(
            content="已记录，请继续。",
            runtime_thread_id=str(thread_id),
            runtime_checkpoint_id=next_checkpoint_id,
        )


class FailOnceCheckpointGateway(CheckpointRecordingGateway):
    async def converse(self, request, **kwargs):
        if not self.run_ids:
            self.thread_ids.append(kwargs["thread_id"])
            self.run_ids.append(kwargs["run_id"])
            self.checkpoint_ids.append(kwargs["checkpoint_id"])
            self.histories.append(kwargs.get("history", ()))
            raise RuntimeError("provider failed after a partial checkpoint")
        return await super().converse(request, **kwargs)


class SemanticEmbeddingGateway:
    model_name = "test-embedding"

    async def embed_documents(self, texts: list[str]) -> list[tuple[float, ...]]:
        return [
            (1.0, 0.0) if "劳动报酬" in text else (0.0, 1.0)
            for text in texts
        ]

    async def embed_query(self, text: str) -> tuple[float, ...]:
        assert "薪资" in text
        return (1.0, 0.0)


class NeverCalledEmbeddingGateway:
    model_name = "never-called"

    async def embed_documents(self, texts):
        raise AssertionError("embedding must be agent-triggered")

    async def embed_query(self, text):
        raise AssertionError("embedding must be agent-triggered")


class PassiveGateway:
    def __init__(self) -> None:
        self.retrieval = None

    async def converse(self, request, *, thread_id, retrieval=None, **kwargs):
        del request, kwargs
        self.retrieval = retrieval
        return GeneratedConversationTurn(
            content="你好，请描述你希望分析的具体情况。",
            runtime_thread_id=str(thread_id),
        )


class ProfileUpdatingGateway:
    def __init__(self, *, fail_after_update: bool = False) -> None:
        self.fail_after_update = fail_after_update

    async def converse(self, request, *, thread_id, case_memory=None, **kwargs):
        del request, kwargs
        assert case_memory is not None
        await case_memory.update_profile(
            CaseProfilePatch(
                case_type="离婚财产分割",
                parties=["用户（妻子）", "配偶（丈夫）"],
                key_facts=["房屋在婚后购买", "房屋登记在双方名下"],
                resolved_missing_information=["房屋购买时间"],
            )
        )
        if self.fail_after_update:
            raise RuntimeError("model failed after staging profile")
        return GeneratedConversationTurn(
            content="已记录房屋情况，请继续补充贷款信息。",
            runtime_thread_id=str(thread_id),
        )


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_persisted_case_material_and_conversation_round_trip(session_factory) -> None:
    context = UserContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        timezone="Asia/Shanghai",
        locale="zh-CN",
    )
    workspace = CaseWorkspaceService(session_factory, context, parse_material_file)
    gateway = RecordingGateway()
    conversation = PersistentLegalConversationService(session_factory, context, gateway)

    case = await workspace.create_case(LegalCaseCreate(title="劳动合同争议"))
    case = await workspace.update_profile(
        case.id,
        CaseProfileUpdate(
            case_type=" 劳动合同争议 ",
            parties=[" 张某（劳动者） ", "某公司", "某公司"],
            claims=["支付拖欠工资"],
            key_facts=["已连续工作三年"],
            disputed_issues=["是否存在欠薪"],
        ),
    )
    material = await workspace.add_material(
        case.id,
        CaseMaterial(title="工资记录", content="公司连续三个月拖欠工资。"),
    )
    first = await conversation.execute(
        case.id,
        CaseConversationTurnRequest(message="公司拖欠工资怎么办？"),
    )
    second = await conversation.execute(
        case.id,
        CaseConversationTurnRequest(message="我已经工作三年。"),
    )
    messages = await conversation.list_messages(case.id)

    assert material.case_id == case.id
    assert case.profile.case_type == "劳动合同争议"
    assert case.profile.parties == ["张某（劳动者）", "某公司"]
    assert first.thread_id == second.thread_id
    assert [message.role for message in messages] == ["user", "assistant", "user", "assistant"]
    assert gateway.histories[0] == ()
    assert [message.role for message in gateway.histories[1]] == ["user", "assistant"]
    assert gateway.histories[1][0].content == "公司拖欠工资怎么办？"
    assert [chunk.reference for chunk in gateway.evidence[0]] == ["M1:C1"]
    assert gateway.requests[0].case_profile == case.profile


@pytest.mark.asyncio
async def test_successful_checkpoint_advances_thread_without_replaying_history(
    session_factory,
) -> None:
    context = UserContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        timezone="Asia/Shanghai",
        locale="zh-CN",
    )
    workspace = CaseWorkspaceService(session_factory, context, parse_material_file)
    gateway = CheckpointRecordingGateway()
    conversation = PersistentLegalConversationService(session_factory, context, gateway)
    case = await workspace.create_case(LegalCaseCreate(title="连续对话案件"))

    first = await conversation.execute(
        case.id,
        CaseConversationTurnRequest(message="第一轮情况"),
    )
    second = await conversation.execute(
        case.id,
        CaseConversationTurnRequest(message="第二轮补充"),
    )

    assert first.thread_id == second.thread_id
    assert first.run_id != second.run_id
    assert gateway.thread_ids == [first.run_id, first.run_id]
    assert gateway.run_ids == [first.run_id, second.run_id]
    assert gateway.checkpoint_ids == [None, "checkpoint-1"]
    assert gateway.histories == [(), ()]
    async with session_factory() as session:
        unit_of_work = LexoraUnitOfWork(session)
        assert await unit_of_work.threads.get_runtime_checkpoint(
            context,
            first.thread_id,
        ) == (first.run_id, "checkpoint-2")


@pytest.mark.asyncio
async def test_failed_first_run_does_not_become_the_next_checkpoint_baseline(
    session_factory,
) -> None:
    context = UserContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        timezone="Asia/Shanghai",
        locale="zh-CN",
    )
    workspace = CaseWorkspaceService(session_factory, context, parse_material_file)
    gateway = FailOnceCheckpointGateway()
    conversation = PersistentLegalConversationService(session_factory, context, gateway)
    case = await workspace.create_case(LegalCaseCreate(title="失败恢复案件"))

    with pytest.raises(RuntimeError, match="partial checkpoint"):
        await conversation.execute(
            case.id,
            CaseConversationTurnRequest(message="第一轮失败"),
        )
    recovered = await conversation.execute(
        case.id,
        CaseConversationTurnRequest(message="重新开始"),
    )

    assert gateway.checkpoint_ids == [None, None]
    assert gateway.thread_ids == gateway.run_ids
    assert gateway.thread_ids[1] == recovered.run_id
    assert gateway.thread_ids[0] != gateway.thread_ids[1]
    assert gateway.histories == [(), ()]


@pytest.mark.asyncio
async def test_retrieval_runs_only_when_agent_calls_a_tool(session_factory) -> None:
    context = UserContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        timezone="Asia/Shanghai",
        locale="zh-CN",
    )
    workspace = CaseWorkspaceService(session_factory, context, parse_material_file)
    gateway = PassiveGateway()
    conversation = PersistentLegalConversationService(
        session_factory,
        context,
        gateway,
        NeverCalledEmbeddingGateway(),
    )
    case = await workspace.create_case(LegalCaseCreate(title="未命名案件"))

    result = await conversation.execute(
        case.id,
        CaseConversationTurnRequest(message="hi"),
    )
    messages = await conversation.list_messages(case.id)

    assert gateway.retrieval is not None
    assert result.assistant_message == "你好，请描述你希望分析的具体情况。"
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[0].run_id == messages[1].run_id == result.run_id


@pytest.mark.asyncio
async def test_agent_profile_updates_are_merged_after_successful_run(session_factory) -> None:
    context = UserContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        timezone="Asia/Shanghai",
        locale="zh-CN",
    )
    workspace = CaseWorkspaceService(session_factory, context, parse_material_file)
    case = await workspace.create_case(LegalCaseCreate(title="离婚房产争议"))
    await workspace.update_profile(
        case.id,
        CaseProfileUpdate(missing_information=["房屋购买时间"]),
    )
    conversation = PersistentLegalConversationService(
        session_factory,
        context,
        ProfileUpdatingGateway(),
    )

    first = await conversation.execute(
        case.id,
        CaseConversationTurnRequest(message="房子婚后买的，登记在我和丈夫名下。"),
    )
    second = await conversation.execute(
        case.id,
        CaseConversationTurnRequest(message="房子婚后买的，登记在我和丈夫名下。"),
    )
    saved = await workspace.get_case(case.id)

    assert first.profile_updated is True
    assert first.case_profile.case_type == "离婚财产分割"
    assert first.case_profile.missing_information == []
    assert second.profile_updated is False
    assert saved.profile.parties == ["用户（妻子）", "配偶（丈夫）"]
    assert saved.profile.key_facts == ["房屋在婚后购买", "房屋登记在双方名下"]


@pytest.mark.asyncio
async def test_staged_profile_update_is_discarded_when_run_fails(session_factory) -> None:
    context = UserContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        timezone="Asia/Shanghai",
        locale="zh-CN",
    )
    workspace = CaseWorkspaceService(session_factory, context, parse_material_file)
    case = await workspace.create_case(LegalCaseCreate(title="失败运行"))
    conversation = PersistentLegalConversationService(
        session_factory,
        context,
        ProfileUpdatingGateway(fail_after_update=True),
    )

    with pytest.raises(RuntimeError, match="model failed"):
        await conversation.execute(
            case.id,
            CaseConversationTurnRequest(message="房子婚后购买。"),
        )

    saved = await workspace.get_case(case.id)
    assert saved.profile == CaseProfile()


@pytest.mark.asyncio
async def test_effective_legal_source_is_retrieved_and_persisted_with_message(
    session_factory,
) -> None:
    context = UserContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        timezone="Asia/Shanghai",
        locale="zh-CN",
    )
    legal_sources = LegalSourceService(session_factory)
    source = await legal_sources.create(
        LegalSourceCreate(
            title="中华人民共和国劳动合同法",
            kind=LegalSourceKind.law,
            issuing_authority="全国人民代表大会常务委员会",
            status=LegalSourceStatus.effective,
            source_name="国家法律法规数据库",
            source_url="https://flk.npc.gov.cn/detail?id=test",
            content="第一条 为了保护劳动者权益。\n第二条 用人单位应当依法支付劳动报酬。",
        )
    )
    workspace = CaseWorkspaceService(session_factory, context, parse_material_file)
    gateway = RecordingGateway()
    conversation = PersistentLegalConversationService(
        session_factory,
        context,
        gateway,
        legal_knowledge=DatabaseLegalKnowledgePort(session_factory),
    )
    case = await workspace.create_case(LegalCaseCreate(title="劳动报酬争议"))

    result = await conversation.execute(
        case.id,
        CaseConversationTurnRequest(message="单位没有支付劳动报酬怎么办？"),
    )
    messages = await conversation.list_messages(case.id)

    assert result.legal_citations
    assert len(result.legal_citations) == 1
    assert len(gateway.legal_authorities[0]) == 2
    assert f"[{result.legal_citations[0].reference}]" in result.assistant_message
    assert result.legal_citations[0].title == source.title
    assert gateway.legal_authorities[0][0].source_url.startswith("https://flk.npc.gov.cn/")
    assert messages[-1].legal_citations == result.legal_citations

    await legal_sources.update(source.id, LegalSourceUpdate(status=LegalSourceStatus.repealed))
    after_repeal = await DatabaseLegalKnowledgePort(session_factory).search(
        "单位没有支付劳动报酬",
        query_embedding=None,
        embedding_model=None,
    )
    assert after_repeal == []


@pytest.mark.asyncio
async def test_approved_legal_source_embeddings_can_be_backfilled(session_factory) -> None:
    legal_sources = LegalSourceService(session_factory)
    await legal_sources.create(
        LegalSourceCreate(
            title="中华人民共和国劳动合同法",
            kind=LegalSourceKind.law,
            issuing_authority="全国人民代表大会常务委员会",
            status=LegalSourceStatus.effective,
            source_name="国家法律法规数据库",
            source_url="https://flk.npc.gov.cn/detail?id=embedding-test",
            content="第一条 保护劳动者权益。\n第二条 用人单位应当支付劳动报酬。",
        )
    )

    indexed = LegalSourceService(session_factory, SemanticEmbeddingGateway())
    first_count = await indexed.backfill_embeddings(batch_size=1)
    second_count = await indexed.backfill_embeddings(batch_size=1)
    chunks = await DatabaseLegalKnowledgePort(session_factory).search(
        "薪资没有到账",
        query_embedding=(1.0, 0.0),
        embedding_model="test-embedding",
    )

    assert first_count == 2
    assert second_count == 0
    assert chunks[0].article_label == "第二条"


@pytest.mark.asyncio
async def test_approved_case_law_is_retrieved_and_persisted_separately(
    session_factory,
) -> None:
    context = UserContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        timezone="Asia/Shanghai",
        locale="zh-CN",
    )
    sources = CaseLawSourceService(session_factory)
    source = await sources.create(
        CaseLawSourceCreate(
            case_number="指导案例240号",
            title="某公司诉某配送员劳动争议案",
            keywords=["劳动", "平台用工", "劳动关系"],
            issuing_authority="最高人民法院",
            source_name="最高人民法院指导性案例",
            source_url="https://www.court.gov.cn/shenpan/xiangqing/450751.html",
            content=(
                "关键词\n劳动 平台用工 劳动关系\n裁判要点\n"
                "根据用工事实判断劳动关系，不能仅依据合同名称。\n"
                "基本案情\n配送员接受平台管理并获得劳动报酬。\n"
                "裁判理由\n平台实施劳动管理的，应依法认定劳动关系。"
            ),
            review_status=LegalSourceReviewStatus.approved,
        )
    )
    workspace = CaseWorkspaceService(session_factory, context, parse_material_file)
    gateway = RecordingGateway()
    conversation = PersistentLegalConversationService(
        session_factory,
        context,
        gateway,
        case_law_knowledge=DatabaseCaseLawKnowledgePort(session_factory),
    )
    case = await workspace.create_case(LegalCaseCreate(title="平台配送员劳动关系争议"))

    result = await conversation.execute(
        case.id,
        CaseConversationTurnRequest(message="平台用工是否构成劳动关系？"),
    )
    messages = await conversation.list_messages(case.id)

    assert result.case_law_citations
    assert len(result.case_law_citations) == 1
    assert len(gateway.case_law_authorities[0]) > 1
    assert f"[{result.case_law_citations[0].reference}]" in result.assistant_message
    assert result.case_law_citations[0].case_number == source.case_number
    assert gateway.case_law_authorities[0]
    assert gateway.case_law_authorities[0][0].source_url == source.source_url
    assert messages[-1].case_law_citations == result.case_law_citations
    assert messages[-1].legal_citations == []


@pytest.mark.asyncio
async def test_case_run_can_be_cancelled_and_remains_visible(session_factory) -> None:
    context = UserContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        timezone="Asia/Shanghai",
        locale="zh-CN",
    )
    workspace = CaseWorkspaceService(session_factory, context, parse_material_file)
    case = await workspace.create_case(LegalCaseCreate(title="待取消分析"))
    async with session_factory() as session:
        unit_of_work = LexoraUnitOfWork(session)
        thread = await unit_of_work.threads.get_or_create_for_case(
            context,
            case_id=case.id,
            title=case.title,
        )
        run = await AgentRunService(unit_of_work).create_run(
            context,
            first_human_message="测试取消",
            thread_id=thread.id,
        )
        await unit_of_work.commit()

    service = CaseRunService(session_factory, context)
    assert (await service.get_latest(case.id)).status.value == "queued"
    cancelled = await service.cancel_active(case.id)

    assert cancelled.run_id == run.id
    assert cancelled.status.value == "cancelled"
    assert (await service.get_latest(case.id)).status.value == "cancelled"


@pytest.mark.asyncio
async def test_persisted_embeddings_enable_semantic_material_retrieval(session_factory) -> None:
    context = UserContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        timezone="Asia/Shanghai",
        locale="zh-CN",
    )
    embeddings = SemanticEmbeddingGateway()
    workspace = CaseWorkspaceService(
        session_factory,
        context,
        parse_material_file,
        embeddings,
    )
    gateway = RecordingGateway()
    conversation = PersistentLegalConversationService(
        session_factory,
        context,
        gateway,
        embeddings,
    )
    case = await workspace.create_case(LegalCaseCreate(title="劳动合同争议"))
    await workspace.add_material(
        case.id,
        CaseMaterial(title="欠薪记录", content="用人单位连续三个月拖欠劳动报酬。"),
    )

    await conversation.execute(
        case.id,
        CaseConversationTurnRequest(message="薪资一直没有到账，我该怎么办？"),
    )

    assert [chunk.reference for chunk in gateway.evidence[0]] == ["M1:C1"]


def test_material_parser_accepts_utf8_text_and_rejects_unknown_formats() -> None:
    assert parse_material_file("事实.md", "交付后付款。".encode()) == "交付后付款。"

    with pytest.raises(MaterialParseError, match="supported material formats"):
        parse_material_file("evidence.exe", b"content")

    with pytest.raises(MaterialParseError, match="extracted material must not exceed"):
        parse_material_file("large.txt", ("证" * (MAX_MATERIAL_CHARS + 1)).encode())
