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
    with pytest.raises(ConnectorError, match="browsentic_action_denied"):
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

    async def turn(task, schema, *, tools, call, mcp, system_prompt):
        assert "page_attachFile" not in mcp[1]
        assert "page_listFiles" not in mcp[1]
        assert {tool["name"] for tool in tools} == {
            "attach_dossier_document",
            "inspect_attachment_fields",
        }
        fields = await call(
            "inspect_attachment_fields",
            {
                "tab": 4,
                "url": "https://example.invalid/form",
                "container": "#application",
            },
        )
        assert fields["success"] and "#resume" in fields["contentItems"][0]["text"]
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

    async def inspect_fields(actual, tab, url, container):
        assert (actual, tab, url, container) == (
            rpc,
            4,
            "https://example.invalid/form",
            "#application",
        )
        return [{"selector": "#resume"}]

    browser.inspect_attachment_fields = inspect_fields
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


def test_unproven_letter_ends_the_turn_and_identifies_the_piece(tmp_path):
    from linkedin_applications.browser import DocumentVerificationError
    from linkedin_applications.obstacles import describe

    browser = Browsentic(tmp_path, [], {})
    state = {
        "dossier": "synthetic",
        "mode": "production",
        "offer": {"url": "https://example.invalid"},
    }

    async def unavailable(*args, **kwargs):
        raise DocumentVerificationError("letter", "session_bytes_unverified")

    browser.fill_async = unavailable
    assert browser.fill(state, []) == {
        "kind": "challenge",
        "text": "browsentic_letter_session_bytes_unverified",
        "scope": "dossier",
    }
    browser.agent_form = unavailable
    result = browser.run_form(state, [])
    diagnostic = describe(result, state)
    assert result["kind"] == "unknown"
    assert diagnostic["cause"] == "piece_incomplete"
    assert "lettre" in diagnostic["observation"]
    assert diagnostic["transmission_attempted"]


def test_follows_delayed_allowed_tab_after_external_apply(tmp_path, monkeypatch):
    browser = Browsentic(tmp_path, [], {})
    observations = iter(
        [
            {"activeTabId": 1},
            {"activeTabId": 2, "tabs": [{"tabId": 2, "url": "about:blank"}]},
            {
                "activeTabId": 2,
                "tabs": [{"tabId": 2, "url": "https://portal.example/apply"}],
            },
        ]
    )

    async def inventory(rpc):
        return next(observations)

    monkeypatch.setattr(browser, "inventory", inventory)
    assert (
        asyncio.run(browser.follow_opened_tab(None, 1, {1}, {"https://portal.example"}))
        == 2
    )


def test_google_option_requires_a_visible_active_control():
    from linkedin_applications.browser import check_google_option

    reported = {"kind": "challenge", "text": "Sign up with Google"}
    page = {
        "interactive": {
            "buttons": [
                {"text": "Agree and create profile"},
                {"text": "Sign up with Google", "state": {"disabled": True}},
            ],
            "links": [{"text": "Sign up with LinkedIn"}],
        },
    }
    assert check_google_option(reported, page)["kind"] == "registration"
    page["interactive"]["buttons"][1]["state"]["disabled"] = False
    assert check_google_option(reported, page) == reported


def test_permanent_registration_approval_handles_new_portals_and_keeps_exclusions():
    from linkedin_applications.browser import registration_decision, registration_result

    portal = "https://www.welcometothejungle.com"
    memory = [{"kind": "registration", "scope": portal, "choice": "allow"}]
    reported = {"kind": "registration", "text": "Créer un compte"}
    assert registration_result(reported, portal, memory)["kind"] == "blocked"
    other = "https://other.example"
    assert registration_result(reported, other, memory)["kind"] == "blocked"
    assert registration_result(reported, other, memory, can_create=True)["kind"] == (
        "account_required"
    )
    memory.append({**memory[0], "choice": "deny"})
    assert registration_decision(memory, portal) == "deny"


def test_native_receipt_requires_live_tab_and_matching_text(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    browser = Browsentic(tmp_path, [], {})
    url = "https://portal.example.org/receipt"

    @asynccontextmanager
    async def session(*args):
        yield object()

    monkeypatch.setattr("linkedin_applications.browser.Session", session)
    browser.connect = AsyncMock()
    browser.current_url = AsyncMock(return_value=url + "?private=secret")
    browser.use = AsyncMock(
        return_value={"structuredContent": {"text": "Candidature reçue pour le poste"}}
    )
    receipt = {"url": url + "?private=secret", "evidence": "Candidature reçue"}
    offer = {"title": "le poste"}
    assert asyncio.run(browser.receipt_observed(3, receipt, offer))
    assert receipt["url"] == url
    assert not asyncio.run(
        browser.receipt_observed(3, {**receipt, "evidence": "invention"}, offer)
    )
    assert not asyncio.run(
        browser.receipt_observed(
            3, {**receipt, "url": "https://other.example.org/receipt"}, offer
        )
    )


def test_hidden_cv_and_letter_fields_get_distinct_form_scoped_selectors():
    from linkedin_applications.upload_fields import file_fields

    result = file_fields(
        """<form><button>Browse</button>
        <input hidden type=file name=resume-upload accept="application/pdf">
        <input hidden type=file name=cover-letter-upload aria-label="Cover letter">
        <input type=file disabled name=old>
        </form>""",
        "#application",
    )
    assert [row["selector"] for row in result] == [
        ':is(#application) input[type=file][name="resume-upload"]',
        ':is(#application) input[type=file][name="cover-letter-upload"]',
    ]
    assert result[0]["accept"] == "application/pdf"
    assert result[1]["label"] == "Cover letter"


def test_ambiguous_anonymous_inputs_require_a_narrower_container():
    from linkedin_applications.upload_fields import file_fields

    html = "<input type=file name=document><input type=file name=document>"
    assert [field["selector"] for field in file_fields(html, "form")] == [None, None]
    assert file_fields("<input type=file hidden>", "#resume-section")[0][
        "selector"
    ] == (":is(#resume-section) input[type=file]")
