import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from linkedin_applications.account_agent import AccountAgent


@pytest.mark.parametrize(
    ("decision", "fresh", "proof", "status", "cause"),
    [
        ("allow", True, "Compte actif", "success", "account_active"),
        (None, True, "Compte actif", "success", "account_active"),
        ("allow", False, "Compte actif", "success", "account_active"),
        ("allow", True, "Preuve inventée", "failure", "unverified_result"),
        ("deny", True, "Compte actif", "failure", "portal_account_approval_required"),
    ],
)
def test_account_agent_controls_native_browser_and_checks_proof(
    tmp_path, decision, fresh, proof, status, cause
):
    domain = "https://portal.example.org"
    page = domain + "/unexpected-signup"
    active = domain + "/active"
    current = page

    async def use(rpc, name, args):
        assert name in {"page_fillInput", "page_extractText"}
        if name == "page_fillInput":
            assert args["target"]["selector"] == "#agent-observed-email"
            assert args["value"] == "test@example.org"
        return {"text": "Compte actif"}

    accounts = SimpleNamespace(
        credentials=Mock(
            return_value=("test@example.org", "protected", "creation_en_cours")
        ),
        claim_registration=Mock(return_value=fresh),
        mark_active=Mock(return_value=True),
    )
    browser = SimpleNamespace(
        cwd=tmp_path,
        command=["browser", "mcp"],
        accounts=accounts,
        confirmations=None,
        current_url=AsyncMock(side_effect=lambda *_: current),
        use=use,
        json_result=lambda value: value,
    )
    agent = AccountAgent(browser)

    async def turn(task, schema, *, call, tools, mcp, system_prompt):
        nonlocal current
        assert "Tu es l’agent Codex" in system_prompt and "test@example.org" not in task
        accounts.claim_registration.assert_called_once_with("dossier", domain)
        assert ("page_clickElement" in mcp[1]) is fresh
        assert "page_navigate" in mcp[1]
        reply = await call(
            "renseigner_identifiants",
            {
                "tab": 1,
                "email_selector": "#agent-observed-email",
                "password_selector": "",
            },
        )
        assert reply["success"] is fresh
        current = active
        return {
            "status": "success",
            "cause": "account_active",
            "evidence": proof,
            "browser_tab": 1,
        }

    agent.codex.turn = AsyncMock(side_effect=turn)
    state = {
        "dossier": "dossier",
        "offer": {"company": "Entreprise test"},
        "account_scope": domain,
        "account_operation": "registration",
    }
    memory = (
        [{"kind": "registration", "scope": domain, "choice": decision}]
        if decision
        else []
    )
    result = asyncio.run(agent.run_on_page(None, state, memory, 1, page))
    assert result["status"] == status
    assert result["cause"] == cause
    assert accounts.mark_active.call_count == int(status == "success")
    if decision == "deny":
        agent.codex.turn.assert_not_called()
    wrong = asyncio.run(
        agent.run_on_page(None, state, memory, 1, "https://other.example.org")
    )
    assert wrong["cause"] == "portal_account_destination_unknown"
