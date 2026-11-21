import asyncio

import pytest
from linkedin_applications.browser import Browsentic
from linkedin_applications.codex import ConnectorError


def test_submit_tool_is_denied_in_preparation_and_checks_tab(tmp_path):
    browser = Browsentic(
        tmp_path,
        ["browsentic", "mcp"],
        {
            "actions": {
                "send": {
                    "phase": "submit",
                    "tool": "page_clickElement",
                    "origin": "https://portal.example",
                    "path": "/review",
                    "query": "job=1",
                    "selector": "#send",
                }
            }
        },
    )
    calls = []

    async def current_url(rpc, tab):
        return "https://portal.example/review?job=2"

    async def use(rpc, tool, args):
        calls.append((tool, args))

    browser.current_url = current_url
    browser.use = use
    with pytest.raises(ConnectorError, match="browsentic_action_denied"):
        asyncio.run(browser.perform(None, 1, {}, "send"))
    with pytest.raises(ConnectorError, match="browsentic_destination_changed"):
        asyncio.run(browser.perform(None, 1, {}, "send", phase="submit"))
    assert not calls


def test_recipe_button_with_reused_selector_is_checked_by_label(tmp_path):
    browser = Browsentic(
        tmp_path,
        ["browsentic", "mcp"],
        {
            "actions": {
                "next": {
                    "phase": "prepare",
                    "tool": "page_clickElement",
                    "origin": "https://portal.example",
                    "path": "/apply",
                    "selector": "footer button",
                    "expected_text": "Suivant",
                }
            }
        },
    )

    async def current_url(rpc, tab):
        return "https://portal.example/apply"

    async def use(rpc, tool, args):
        assert tool == "page_getPageInfo"
        return {
            "structuredContent": {
                "interactive": {
                    "buttons": [
                        {"selector": "footer button", "text": "Envoyer la candidature"}
                    ]
                }
            }
        }

    browser.current_url = current_url
    browser.use = use
    with pytest.raises(ConnectorError, match="browsentic_action_target_changed"):
        asyncio.run(browser.perform(None, 1, {}, "next"))
