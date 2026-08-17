from __future__ import annotations

from unittest.mock import Mock

from north import AppConfig, ConversationTitleService, FunctionPlugin, install_plugins
from north.agents.middlewares import TitleMiddleware

from lexora_ai.infrastructure.agent_plugins import build_lexora_plugins
from lexora_ai.infrastructure.case_analyst import build_case_analyst_definition
from lexora_ai.infrastructure.legal_researcher import build_legal_researcher_definition
from lexora_ai.infrastructure.legal_turn_middleware import LegalDelegationMiddleware


def test_lexora_composition_root_exposes_explicit_plugin_roles() -> None:
    authority = Mock()
    authority.name = "search_legal_authorities"
    plugins = build_lexora_plugins(
        supervisor_tools=[Mock(name="search_case_materials")],
        definitions=[
            build_case_analyst_definition(),
            build_legal_researcher_definition([authority]),
        ],
    )

    assert [plugin.plugin_id for plugin in plugins] == [
        "lexora.tools",
        "lexora.subagents",
        "lexora.title",
    ]
    assert all(plugin.requires == ("north.runtime",) for plugin in plugins)
    assert all(plugin.scopes == ("lead_agent",) for plugin in plugins)


def test_lexora_title_plugin_registers_provider_service_and_middleware() -> None:
    model = Mock()
    plugins = (
        FunctionPlugin(plugin_id="north.runtime", installer=lambda _context: None),
        *build_lexora_plugins(
            supervisor_tools=[],
            definitions=[build_case_analyst_definition()],
        ),
    )

    installation = install_plugins(
        plugins,
        config=AppConfig(model_name="openai:gpt-test"),
        scope="lead_agent",
        model=model,
        system_prompt="Test prompt.",
        tools=[],
    )

    assert installation.context.providers["conversation_title"] is model
    assert isinstance(
        installation.context.services["conversation_title"],
        ConversationTitleService,
    )
    assert any(
        isinstance(middleware, TitleMiddleware)
        for middleware in installation.context.middlewares
    )
    assert any(
        isinstance(middleware, LegalDelegationMiddleware)
        for middleware in installation.context.middlewares
    )
