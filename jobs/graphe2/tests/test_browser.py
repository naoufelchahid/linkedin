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


def test_native_turn_selects_the_dossier_role_instead_of_a_file_id(
    tmp_path, monkeypatch
):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    browser = Browsentic(tmp_path, [], {})
    calls = []
    rpc = object()
    state = {"dossier": "synthetic", "mode": "production", "cv": "frozen.pdf"}

    @asynccontextmanager
    async def session(*args):
        yield rpc

    async def connect(actual):
        assert actual is rpc

    async def attach(actual, tab, url, current, piece, target):
        assert actual is rpc and current is state
        calls.append((tab, url, piece, target))

    async def turn(task, schema, *, tools, call, mcp):
        assert "page_attachFile" not in mcp[1]
        assert "page_listFiles" not in mcp[1]
        name = tools[0]["name"]
        result = await call(
            name,
            {
                "piece": "cv",
                "tab": 4,
                "url": "https://example.invalid/form",
                "selector": "#resume",
            },
        )
        assert result["success"]
        return {"kind": "question", "browser_tab": 4, "confirmation_url": ""}

    monkeypatch.setattr("linkedin_applications.browser.Session", session)
    browser.connect = connect
    browser.attach_document = attach
    browser.codex = SimpleNamespace(turn=turn)
    assert browser.run_form(state, [])["kind"] == "question"
    assert calls == [(4, "https://example.invalid/form", "cv", {"selector": "#resume"})]


def test_obstacle_check_reads_same_tab_and_page_before_resume(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    browser = Browsentic(tmp_path, [], {})
    state = {"browser_tab": 7, "offer": {"title": "Poste", "company": "Fixture"}}
    diagnostic = {"portal": "fixture.invalid", "condition": "Champ disponible."}

    @asynccontextmanager
    async def session(*args):
        yield object()

    monkeypatch.setattr("linkedin_applications.browser.Session", session)
    browser.connect = AsyncMock()
    form = "https://fixture.invalid/form"
    browser.current_url = AsyncMock(
        side_effect=[form, form, form, form + "/other", "https://other.invalid/"]
    )
    browser.codex.turn = AsyncMock(return_value={"checked": True})

    assert browser.obstacle_cleared(state, diagnostic)
    assert not browser.obstacle_cleared(state, diagnostic)
    assert not browser.obstacle_cleared(state, diagnostic)
    assert browser.codex.turn.await_count == 2
    for call in browser.codex.turn.await_args_list:
        assert set(call.kwargs["mcp"][1]) == {"page_getPageInfo", "page_extractText"}
