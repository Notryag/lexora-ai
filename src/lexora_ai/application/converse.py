from __future__ import annotations

from uuid import uuid4

from lexora_ai.application.ports import LegalConversationGateway
from lexora_ai.domain import ConversationTurnRequest, ConversationTurnResult


class LegalConversationService:
    def __init__(self, gateway: LegalConversationGateway) -> None:
        self._gateway = gateway

    async def execute(self, request: ConversationTurnRequest) -> ConversationTurnResult:
        thread_id = request.thread_id or uuid4()
        generated = await self._gateway.converse(request, thread_id=thread_id)
        content = generated.content.strip()
        if not content:
            raise RuntimeError("conversation provider returned an empty response")
        if generated.runtime_thread_id != str(thread_id):
            raise RuntimeError("conversation provider returned a mismatched thread ID")
        return ConversationTurnResult(
            thread_id=thread_id,
            assistant_message=content,
            material_count=len(request.materials),
        )

