from __future__ import annotations

from unittest.mock import Mock

from north import AppConfig, FunctionPlugin, install_plugins
from north.agents.middlewares import TitleMiddleware

from lexora_ai.infrastructure.agent_plugins import build_lexora_plugins
from lexora_ai.infrastructure.case_analyst import build_case_analyst_definition
from lexora_ai.infrastructure.legal_researcher import build_legal_researcher_definition


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


def test_lexora_title_plugin_registers_north_title_middleware() -> None:
    plugins = (
        FunctionPlugin(plugin_id="north.runtime", installer=lambda _context: None),
        *build_lexora_plugins(supervisor_tools=[], definitions=[]),
    )

    installation = install_plugins(
        plugins,
        config=AppConfig(model_name="openai:gpt-test"),
        scope="lead_agent",
        model=Mock(),
        system_prompt="Test prompt.",
        tools=[],
    )

    assert any(isinstance(item, TitleMiddleware) for item in installation.context.middlewares)
    installation.dispose()
