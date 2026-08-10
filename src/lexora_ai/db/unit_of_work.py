from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from lexora_ai.db.case_law_repository import CaseLawRepository
from lexora_ai.db.case_repository import CaseRepository
from lexora_ai.db.legal_source_repository import LegalSourceRepository
from lexora_ai.db.platform_repositories import (
    AgentRunEventRepository,
    AgentRunRepository,
    ConversationStateRepository,
    ConversationThreadRepository,
    IdempotencyRepository,
)


class LexoraUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.cases = CaseRepository(session)
        self.case_law = CaseLawRepository(session)
        self.legal_sources = LegalSourceRepository(session)
        self.threads = ConversationThreadRepository(session)
        self.states = ConversationStateRepository(session)
        self.runs = AgentRunRepository(session)
        self.events = AgentRunEventRepository(session)
        self.idempotency = IdempotencyRepository(session)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
