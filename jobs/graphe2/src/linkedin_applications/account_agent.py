"""Pilotage natif d’un compte par Codex App Server."""

import asyncio
import json
from importlib.resources import files

from jsonschema import ValidationError
from psycopg import Error as DatabaseError

from .accounts import registration_decision
from .codex import Codex, ConnectorError, Session, codex_environment
from .confirmations import origin
from .writer import dossier_context, schema

SYSTEM_PROMPT = (
    files(__package__)
    .joinpath("resources/account-system.txt")
    .read_text(encoding="utf-8")
)
RESULT = schema(
    status="string", cause="string", evidence="string", browser_tab="integer"
)
RESULT["properties"]["status"]["enum"] = ["success", "failure"]
RESULT["properties"]["cause"]["enum"] = [
    "account_active",
    "confirmation_pending",
    "human_verification",
    "additional_consent",
    "missing_information",
    "portal_rejected",
    "unverified_result",
    "technical_error",
]


def outcome(status, cause, tab=None):
    result = {"status": status, "cause": cause}
    if tab:
        result["browser_tab"] = tab
    return result


def tool_result(success, code):
    return {"success": success, "contentItems": [{"type": "inputText", "text": code}]}


class AccountAgent:
    def __init__(self, browser):
        self.browser = browser
        self.codex = Codex(browser.cwd / "account")

    async def run(self, state, memory, tab):
        browser = self.browser
        try:
            async with (
                asyncio.timeout(120),
                Session(browser.command, self.codex.cwd, codex_environment()) as rpc,
            ):
                await browser.connect(rpc)
                inventory = await browser.inventory(rpc)
                url = next(
                    (
                        item.get("url")
                        for item in inventory.get("tabs", [])
                        if item.get("tabId") == tab
                    ),
                    None,
                )
                if not url:
                    return outcome("failure", "account_tab_missing")
                return await self.run_on_page(rpc, state, memory, tab, url)
        except ConnectorError as exc:
            return outcome("failure", str(exc))
        except (OSError, TimeoutError, ValueError, ValidationError, DatabaseError):
            return outcome("failure", "technical_error")

    async def run_on_page(self, rpc, state, memory, tab, url):
        # Import différé : ces capacités sont aussi celles du navigateur d’offre.
        from .browser import FORM_TOOLS, REVIEW_TOOLS

        browser = self.browser
        accounts = browser.accounts
        dossier = state["dossier"]
        scope = origin(url)
        if not scope or scope != state.get("account_scope"):
            return outcome("failure", "portal_account_destination_unknown")
        if scope == "https://accounts.google.com":
            return outcome("failure", "human_verification", tab)
        registration = state.get("account_operation") == "registration"
        read_only = False
        credentials = None
        if registration:
            if registration_decision(memory, scope, permanent=True) != "allow":
                return outcome("failure", "portal_account_approval_required")
            if not accounts:
                return outcome("failure", "account_storage_unavailable")
            credentials = accounts.credentials(dossier, url, memory, native=True)
            if credentials[2] == "actif":
                registration = False
            else:
                # Réserver avant de donner les outils capables de créer un compte.
                read_only = not accounts.claim_registration(dossier, scope)

        tools = [
            {
                "name": "renseigner_identifiants",
                "description": "Insérer les identifiants dans les champs que tu as observés. "
                "Laisse vide le sélecteur d’un champ absent.",
                "inputSchema": schema(
                    tab="integer", email_selector="string", password_selector="string"
                ),
            },
            {
                "name": "recevoir_activation",
                "description": "Chercher la confirmation du portail dans Thunderbird. "
                "Indique le sélecteur observé du code, ou laisse-le vide pour un lien.",
                "inputSchema": schema(tab="integer", code_selector="string"),
            },
        ]
        if read_only and browser.confirmations:
            tools.append(
                {
                    "name": "valider_activation",
                    "description": "Cliquer le bouton que tu viens d’observer pour confirmer le code du compte en attente.",
                    "inputSchema": schema(tab="integer", selector="string"),
                }
            )
        linked = credentials is not None
        activation_clicked = False

        async def call(name, args):
            nonlocal credentials, linked, activation_clicked
            try:
                current_tab = args["tab"]
                current = await browser.current_url(rpc, current_tab)
                if origin(current) != scope:
                    return tool_result(False, "portal_account_destination_changed")
                if name == "renseigner_identifiants" and accounts and not read_only:
                    if credentials is None:
                        credentials = accounts.credentials(
                            dossier,
                            url,
                            memory,
                            native=True,
                            create=False,
                        )
                        linked = True
                    for selector, value in zip(
                        (args["email_selector"], args["password_selector"]),
                        credentials[:2],
                        strict=True,
                    ):
                        if selector:
                            if await browser.current_url(rpc, current_tab) != current:
                                return tool_result(
                                    False, "portal_account_destination_changed"
                                )
                            await browser.use(
                                rpc,
                                "page_fillInput",
                                {
                                    "target": {"selector": selector},
                                    "value": value,
                                },
                            )
                    return tool_result(True, "identifiants_renseignes")
                if name == "recevoir_activation" and browser.confirmations:
                    result = await browser.confirmations.activation_for_agent(
                        dossier,
                        scope,
                        current_tab,
                        current,
                        args["code_selector"],
                    )
                    return tool_result(bool(result), result or "confirmation_pending")
                if (
                    name == "valider_activation"
                    and read_only
                    and browser.confirmations
                    and not activation_clicked
                ):
                    activation_clicked = (
                        await browser.confirmations.validate_agent_code(
                            rpc,
                            dossier,
                            scope,
                            current_tab,
                            current,
                            args["selector"],
                        )
                    )
                    return tool_result(
                        activation_clicked,
                        "activation_clicked"
                        if activation_clicked
                        else "confirmation_pending",
                    )
            except (ConnectorError, DatabaseError, OSError, TimeoutError):
                return tool_result(False, "account_tool_unavailable")
            return tool_result(False, "account_action_unavailable")

        result = await self.codex.turn(
            "Traite l’accès au compte sur ce portail et vérifie le résultat. "
            + json.dumps(
                {
                    **dossier_context(state),
                    "page": url,
                    "onglet": tab,
                    "operation": "verification"
                    if read_only
                    else "registration"
                    if registration
                    else "login",
                    "activation_mail_disponible": bool(browser.confirmations),
                },
                ensure_ascii=False,
            ),
            RESULT,
            tools=tools,
            call=call,
            mcp=(browser.command, REVIEW_TOOLS if read_only else FORM_TOOLS),
            system_prompt=SYSTEM_PROMPT,
        )
        observed_tab = result["browser_tab"] or tab
        if observed_tab <= 0:
            return outcome("failure", "unverified_result")
        if result["status"] != "success":
            return outcome("failure", result["cause"], observed_tab)
        current = await browser.current_url(rpc, observed_tab)
        if origin(current) != scope or not result["evidence"].strip():
            return outcome("failure", "unverified_result", observed_tab)
        page = browser.json_result(await browser.use(rpc, "page_extractText", {}))
        content = page.get("text") or page.get("content") or ""
        if (
            " ".join(result["evidence"].split()) not in " ".join(content.split())
            or await browser.current_url(rpc, observed_tab) != current
        ):
            return outcome("failure", "unverified_result", observed_tab)
        if linked and not accounts.mark_active(dossier, scope):
            return outcome("failure", "portal_account_ambiguous", observed_tab)
        return outcome("success", "account_active", observed_tab)
