from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from north import (
    AgentDefinition,
    FunctionPlugin,
    PluginContext,
    RegistrationHandle,
    TitleMiddleware,
)

from lexora_ai.infrastructure.legal_turn_middleware import LegalDelegationMiddleware


def _register_all(context: PluginContext, values: Sequence[Any]) -> RegistrationHandle | None:
    handles = [context.register_tool(value) for value in values]
    return RegistrationHandle(lambda: [handle.dispose() for handle in reversed(handles)])


def build_lexora_plugins(
    *,
    supervisor_tools: Sequence[Any],
    definitions: Sequence[AgentDefinition],
) -> tuple[FunctionPlugin, ...]:
    """Compose Lexora's lead-agent plugins for one conversation run."""

    def install_tools(context: PluginContext) -> RegistrationHandle | None:
        return _register_all(context, supervisor_tools)

    def install_subagents(context: PluginContext) -> RegistrationHandle | None:
        handles = [context.register_agent_definition(definition) for definition in definitions]
        handles.append(context.register_middleware(LegalDelegationMiddleware()))
        return RegistrationHandle(lambda: [handle.dispose() for handle in reversed(handles)])

    def install_title(context: PluginContext) -> RegistrationHandle:
        return context.register_middleware(TitleMiddleware(model=context.model, max_chars=32))

    return (
        FunctionPlugin(
            plugin_id="lexora.tools",
            installer=install_tools,
            requires=("north.runtime",),
            scopes=("lead_agent",),
        ),
        FunctionPlugin(
            plugin_id="lexora.subagents",
            installer=install_subagents,
            requires=("north.runtime",),
            scopes=("lead_agent",),
        ),
        FunctionPlugin(
            plugin_id="lexora.title",
            installer=install_title,
            requires=("north.runtime",),
            scopes=("lead_agent",),
        ),
    )


__all__ = ["build_lexora_plugins"]
