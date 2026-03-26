from __future__ import annotations

from prompt_toolkit.keys import Keys  # type: ignore[import-not-found]
from questionary import Choice

from app.cli.wizard.prompts import checkbox, select


def test_select_prompt_registers_tab_navigation() -> None:
    question = select("Provider", [Choice("Anthropic", value="anthropic"), Choice("OpenAI", value="openai")])
    key_bindings = question.application.key_bindings
    assert key_bindings is not None
    bindings = {binding.keys for binding in key_bindings.bindings}

    assert (Keys.ControlI,) in bindings
    assert (Keys.BackTab,) in bindings


def test_checkbox_prompt_registers_tab_navigation() -> None:
    question = checkbox("Integrations", [Choice("Grafana", value="grafana"), Choice("Slack", value="slack")])
    key_bindings = question.application.key_bindings
    assert key_bindings is not None
    bindings = {binding.keys for binding in key_bindings.bindings}

    assert (Keys.ControlI,) in bindings
    assert (Keys.BackTab,) in bindings
