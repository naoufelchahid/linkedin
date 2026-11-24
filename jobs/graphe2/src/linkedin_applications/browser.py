"""Expose à Codex les opérations Browsentic autorisées pour le formulaire courant."""

import asyncio
import json
import re
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .account_agent import AccountAgent
from .accounts import registration_decision
from .codex import Codex, ConnectorError, Session, codex_environment
from .graph import fingerprint
from .mandate import TEXT as SUBMISSION_MANDATE
from .obstacles import SIGNALS, STAGES
from .upload_fields import file_fields
from .urls import offer_url
from .writer import dossier_context, schema

PREPARATION_PROMPT = (
    files(__package__)
    .joinpath("resources/browser-system.txt")
    .read_text(encoding="utf-8")
)
READ = {"page_getPageInfo", "page_extractText"}
PREPARATION = {
    "page_clickElement",
    "page_fillInput",
    "page_selectOption",
    "page_attachFile",
    "page_navigate",
}

REVIEW_TOOLS = (
    "page_getPageInfo",
    "page_extractText",
    "page_waitForElement",
    "page_screenshot",
    "page_switchFrame",
    "page_switchTab",
    "page_openTab",
    "page_navigate",
    "page_scroll",
)
FORM_TOOLS = REVIEW_TOOLS + (
    "page_clickElement",
    "page_fillInput",
    "page_selectOption",
    "page_trustedClick",
    "page_focusInput",
    "page_typeText",
    "page_pressKey",
    "page_submitForm",
)

DOCUMENT_TOOLS = (
    {
        "name": "attach_dossier_document",
        "description": "Joindre le CV ou la lettre figée au sélecteur observé, avec contrôle de l’URL et de l’empreinte.",
        "inputSchema": schema(
            piece="string", tab="integer", url="string", selector="string"
        ),
    },
    {
        "name": "inspect_attachment_fields",
        "description": "Lister les champs de fichier visibles et masqués dans le formulaire ou le conteneur observé.",
        "inputSchema": schema(tab="integer", url="string", container="string"),
    },
)
DOCUMENT_TOOL_NAMES = {tool["name"] for tool in DOCUMENT_TOOLS}

AGENT_RESULT = schema(
    kind="string",
    text="string",
    scope="string",
    browser_tab="integer",
    transmission_attempted="boolean",
    evidence="string",
    confirmation_url="string",
    sent_at="string",
    signal="string",
    stage="string",
    portal_origin="string",
)
AGENT_RESULT["properties"]["signal"]["enum"] = ["aucun", *SIGNALS]
AGENT_RESULT["properties"]["stage"]["enum"] = list(STAGES)
AGENT_RESULT["properties"]["kind"]["enum"] = [
    "submitted",
    "unknown",
    "blocked",
    "question",
    "letter",
    "registration",
    "challenge",
    "account_confirmation",
    "account_required",
]


def registration_result(result, scope, memory, *, can_create=False):
    choice = registration_decision(memory, scope, permanent=True)
    if choice == "allow" and can_create:
        return {**result, "scope": scope, "kind": "account_required"}
    reason = (
        "Inscription refusée dans la mémoire de ce portail."
        if choice == "deny"
        else "Inscription autorisée par l’accord permanent. La création du compte s’effectue en production."
    )
    return {**result, "scope": scope, "kind": "blocked", "text": reason}


def check_google_option(result, page):
    controls = page.get("interactive", {})
    labels = [
        " ".join((row.get("text") or "").split())
        for section in ("buttons", "links")
        for row in controls.get(section, [])
        if not row.get("state", {}).get("disabled")
    ]
    if any(re.search(r"\bgoogle\b", label, re.IGNORECASE) for label in labels):
        return result
    if "Agree and create profile" in labels:
        return {
            **result,
            "kind": "registration",
            "text": (
                "Le formulaire propose l’inscription par e-mail via « Agree and create profile ». "
                "Le site demande d’accepter ses conditions et sa politique de confidentialité."
            ),
        }
    return {
        **result,
        "kind": "blocked",
        "text": "L’option Google annoncée est introuvable parmi les boutons actifs de cet écran.",
    }


class DocumentVerificationError(ConnectorError):
    def __init__(self, piece, reason):
        super().__init__(f"browsentic_{piece}_{reason}")
        self.piece = piece


class Browsentic:
    # Ce MCP cible l’onglet actif. Pendant une intervention, le worker préserve le focus.
    background_safe = False
    native_submission = True

    def __init__(self, data, command, policy, *, policy_path=None, documents=None):
        self.cwd = Path(data) / "browser"
        self.codex = Codex(self.cwd)
        self.command = command
        self.actions = policy.get("actions", {})
        self.verifications = policy.get("verification", [])
        self.confirmations = None
        self.accounts = None
        self.documents = documents
        self.policy_path = Path(policy_path) if policy_path else None
        self.files = policy.get("files", {})
        self.tabs = {}

    async def use(self, rpc, name, arguments):
        result = await rpc.request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise ConnectorError("browsentic_" + name)
        return result

    @staticmethod
    def json_result(result):
        if result.get("structuredContent"):
            return result["structuredContent"]
        text = result["content"][0]["text"]
        try:
            return json.loads(text)
        except ValueError:
            # Le serveur peut entourer le JSON avec sa balise de données.
            start, end = text.find("{"), text.rfind("}")
            if start < 0:
                raise ConnectorError("browsentic_result_invalid") from None
            return json.loads(text[start : end + 1])

    async def inventory(self, rpc):
        return self.json_result(await self.use(rpc, "page_switchTab", {}))

    async def select(self, rpc, state):
        dossier = state["dossier"]
        tab = self.tabs.get(dossier, state.get("browser_tab"))
        if tab is not None and not any(
            row.get("tabId") == tab
            for row in (await self.inventory(rpc)).get("tabs", [])
        ):
            tab = None
        if tab is None:
            opened = self.json_result(
                await self.use(
                    rpc,
                    "page_openTab",
                    {
                        "url": state["offer"]["url"],
                        "active": True,
                    },
                )
            )
            tab = opened["tabId"]
        else:
            await self.use(rpc, "page_switchTab", {"tabId": tab})
        self.tabs[dossier] = tab
        return tab

    async def follow_opened_tab(self, rpc, previous, known_tabs, origins):
        deadline = asyncio.get_running_loop().time() + 2
        while True:
            current = await self.inventory(rpc)
            active = current.get("activeTabId")
            if active is not None and active != previous:
                if active in known_tabs:
                    raise ConnectorError("browsentic_tab_changed")
                row = next(
                    (
                        tab
                        for tab in current.get("tabs", [])
                        if tab.get("tabId") == active
                    ),
                    {},
                )
                url = current.get("url") or current.get("currentUrl") or row.get("url")
                if url and url != "about:blank":
                    target = urlsplit(url)
                    if f"{target.scheme}://{target.netloc}" not in origins:
                        raise ConnectorError("browsentic_destination_unknown")
                    return active
            if asyncio.get_running_loop().time() >= deadline:
                if active == previous:
                    return previous
                raise ConnectorError("browsentic_destination_unknown")
            await asyncio.sleep(0.1)

    async def current_url(self, rpc, tab):
        current = await self.inventory(rpc)
        if current.get("activeTabId") != tab:
            raise ConnectorError("browsentic_tab_changed")
        url = current.get("url") or current.get("currentUrl")
        if not url:
            for row in current.get("tabs", []):
                if row.get("tabId", row.get("id")) == tab:
                    url = row.get("url")
                    break
        if not url:
            raise ConnectorError("browsentic_url_unknown")
        return url

    @staticmethod
    def matches(url, rule):
        path = urlsplit(url)
        if "query" in rule and rule["query"] != path.query:
            return False
        expected = urlsplit(rule["origin"] + rule["path"])
        if expected.hostname == "www.linkedin.com" and expected.path.startswith(
            "/jobs/view/"
        ):
            target = urlsplit(offer_url(url))
            linkedin_offer = urlsplit(offer_url(expected.geturl()))
            return (target.scheme, target.netloc, target.path) == (
                linkedin_offer.scheme,
                linkedin_offer.netloc,
                linkedin_offer.path,
            )
        return (path.scheme, path.netloc, path.path) == (
            expected.scheme,
            expected.netloc,
            expected.path,
        )

    async def attach_document(self, rpc, tab, url, state, piece, target):
        if piece not in {"cv", "letter"}:
            raise ConnectorError("browsentic_piece_unknown")
        digest = state.get(piece + "_hash")
        if self.documents:
            path = self.documents.dossier_document(state["dossier"], piece)
            if path and not digest:
                digest = path.stem
        else:
            path = Path(state[piece]) if state.get(piece) else None
        if path is None or not path.is_file():
            raise DocumentVerificationError(piece, "missing")
        if not digest or digest != fingerprint(path):
            raise DocumentVerificationError(piece, "integrity")
        files = self.files
        if self.policy_path is not None:
            try:
                files = json.loads(self.policy_path.read_text()).get("files", {})
            except (OSError, ValueError):
                raise DocumentVerificationError(piece, "registry_unavailable") from None
        entry = files.get(digest)
        if isinstance(entry, str):
            entry = {"fileId": entry}
        if not isinstance(entry, dict):
            raise DocumentVerificationError(piece, "not_registered")
        if entry.get("fileId"):
            key, tool, rows = "fileId", "page_listFiles", "files"
        elif entry.get("downloadId"):
            key, tool, rows = "downloadId", "page_listDownloads", "downloads"
        else:
            raise DocumentVerificationError(piece, "not_registered")
        if await self.current_url(rpc, tab) != url:
            raise ConnectorError("browsentic_destination_changed")
        inventory = self.json_result(await self.use(rpc, tool, {}))
        if not any(
            row.get("id") == entry[key] and row.get("size") == path.stat().st_size
            for row in inventory.get(rows, [])
        ):
            raise DocumentVerificationError(piece, "reference_expired")
        # Capacité du transport injecté, distincte du protocole MCP Browsentic.
        # L’envoi doit réutiliser les octets épinglés, jamais résoudre l’ID à nouveau.
        pin = getattr(rpc, "pin_attachment", None)
        if pin is None:
            tools = (await rpc.request("tools/list")).get("tools", [])
            attach = next(
                (tool for tool in tools if tool["name"] == "page_attachFile"), {}
            )
            properties = attach.get("inputSchema", {}).get("properties", {})
            if not {"expectedSha256", "expectedUrl"} <= properties.keys():
                raise DocumentVerificationError(piece, "session_bytes_unverified")
            if await self.current_url(rpc, tab) != url:
                raise ConnectorError("browsentic_destination_changed")
            response = await self.use(
                rpc,
                "page_attachFile",
                {
                    key: entry[key],
                    "expectedSha256": digest,
                    "expectedUrl": url,
                    "target": target,
                },
            )
            result = self.json_result(response)
            if result.get("attached") is not True or result.get("sha256") != digest:
                raise DocumentVerificationError(piece, "session_bytes_unverified")
            return response
        content, send = await pin({key: entry[key]})
        if not isinstance(content, bytes) or sha256(content).hexdigest() != digest:
            raise DocumentVerificationError(piece, "session_bytes_mismatch")
        if await self.current_url(rpc, tab) != url:
            raise ConnectorError("browsentic_destination_changed")
        return await send(target, content)

    async def inspect_attachment_fields(self, rpc, tab, url, container):
        if not container.strip() or await self.current_url(rpc, tab) != url:
            raise ConnectorError("browsentic_destination_changed")
        page = self.json_result(
            await self.use(
                rpc,
                "page_extractText",
                {
                    "target": {"selector": container},
                    "format": "html",
                    "maxLength": 50000,
                },
            )
        )
        html = page.get("content")
        if not isinstance(html, str):
            raise ConnectorError("browsentic_upload_markup_unavailable")
        if page.get("truncated"):
            raise ConnectorError("browsentic_upload_narrow_container")
        if await self.current_url(rpc, tab) != url:
            raise ConnectorError("browsentic_destination_changed")
        return file_fields(html, page.get("source") or container)

    async def document_tool(self, rpc, state, name, args):
        if name == "inspect_attachment_fields":
            fields = await self.inspect_attachment_fields(
                rpc, args["tab"], args["url"], args["container"]
            )
            return json.dumps({"file_fields": fields}, ensure_ascii=False)
        if name == "attach_dossier_document":
            await self.attach_document(
                rpc,
                args["tab"],
                args["url"],
                state,
                args["piece"],
                {"selector": args["selector"]},
            )
            return "Pièce jointe avec empreinte vérifiée. Relis le nom affiché et les erreurs du formulaire."
        raise ConnectorError("browsentic_action_denied")

    async def perform(self, rpc, tab, state, name, value=None, phase="prepare"):
        rule = self.actions.get(name, {})
        if (
            phase != "prepare"
            or rule.get("phase") != phase
            or rule.get("tool") not in PREPARATION
        ):
            raise ConnectorError("browsentic_action_denied")
        url = await self.current_url(rpc, tab)
        if not self.matches(url, rule):
            raise ConnectorError("browsentic_destination_changed")
        observed = None
        if expected := rule.get("expected_text"):
            page = self.json_result(
                await self.use(rpc, "page_getPageInfo", {"maxPerKind": 80})
            )
            options = page["interactive"]
            matches = [
                item
                for group in ("buttons", "links", "fields")
                for item in options.get(group, [])
                if item.get("selector") == rule["selector"]
                and " ".join((item.get("text") or "").split()) == expected
                and not item.get("state", {}).get("disabled")
            ]
            if len(matches) != 1:
                raise ConnectorError("browsentic_action_target_changed")
            observed = matches[0]
            if await self.current_url(rpc, tab) != url:
                raise ConnectorError("browsentic_destination_changed")
        if rule["tool"] == "page_navigate":
            if not observed or not observed.get("href"):
                raise ConnectorError("browsentic_navigation_link_missing")
            href = urlsplit(observed["href"])
            if (
                href.hostname == "www.linkedin.com"
                and href.path.rstrip("/") == "/safety/go"
            ):
                href = urlsplit(parse_qs(href.query).get("url", [""])[0])
            dest = urlsplit(rule["destination_url"])
            if dest.scheme != "https" or (
                href.scheme,
                href.netloc,
                href.path.rstrip("/"),
            ) != (dest.scheme, dest.netloc, dest.path.rstrip("/")):
                raise ConnectorError("browsentic_destination_changed")
            return await self.use(rpc, "page_navigate", {"url": dest.geturl()})
        args = {"target": {"selector": rule["selector"]}}
        if rule["tool"] == "page_attachFile":
            return await self.attach_document(
                rpc, tab, url, state, rule["piece"], args["target"]
            )
        if field := rule.get("value_property"):
            if value is None:
                raise ConnectorError("browsentic_field_value_missing")
            args[field] = value
        return await self.use(rpc, rule["tool"], args)

    async def connect(self, rpc):
        await rpc.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "linkedin_applications", "version": "0.1.0"},
            },
        )
        await rpc.write({"method": "notifications/initialized"})

    async def fill_async(self, state, memory):
        async with (
            asyncio.timeout(200),
            Session(self.command, self.cwd, codex_environment()) as rpc,
        ):
            await self.connect(rpc)
            tab = await self.select(rpc, state)
            available = (await rpc.request("tools/list"))["tools"]
            definitions = [
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "inputSchema": tool["inputSchema"],
                }
                for tool in available
                if tool["name"] in READ
            ]
            definitions.extend(DOCUMENT_TOOLS)
            definitions.append(
                {
                    "name": "form_action",
                    "description": "Exécuter une action de préparation vérifiée.",
                    "inputSchema": schema(
                        action="string", value=["string", "boolean", "null"]
                    ),
                }
            )

            async def call(name, params):
                nonlocal tab
                try:
                    await self.current_url(rpc, tab)
                    if name == "form_action":
                        action = params["action"]
                        rule = self.actions.get(action, {})
                        phase = rule.get("phase")
                        if phase != "prepare":
                            raise ConnectorError("browsentic_action_denied")
                        before = None
                        if rule.get("opens_tab"):
                            before = {
                                row["tabId"]
                                for row in (await self.inventory(rpc)).get("tabs", [])
                            }
                        result = await self.perform(
                            rpc, tab, state, action, params.get("value"), phase
                        )
                        if before is not None:
                            tab = await self.follow_opened_tab(
                                rpc,
                                tab,
                                before,
                                rule.get("destination_origins", []),
                            )
                            self.tabs[state["dossier"]] = tab
                    elif name in DOCUMENT_TOOL_NAMES and params["tab"] == tab:
                        value = await self.document_tool(rpc, state, name, params)
                        result = {"content": [{"type": "text", "text": value}]}
                    elif name in READ:
                        result = await self.use(rpc, name, params)
                    else:
                        raise ConnectorError("browsentic_action_denied")
                except DocumentVerificationError:
                    raise
                except ConnectorError as exc:
                    return {
                        "success": False,
                        "contentItems": [{"type": "inputText", "text": str(exc)}],
                    }
                return {
                    "success": True,
                    "contentItems": [
                        {"type": "inputText", "text": block["text"]}
                        for block in result["content"]
                        if block["type"] == "text"
                    ],
                }

            actions = {
                name: {k: rule[k] for k in ("description", "phase", "origin", "path")}
                for name, rule in self.actions.items()
            }
            result = await self.codex.turn(
                "Prépare le formulaire de cette offre et retourne son état. Données :\n"
                + json.dumps(
                    {
                        **dossier_context(state),
                        "browser_tab": tab,
                        "memory": memory,
                        "mode": state["mode"],
                        "actions": actions,
                        "cv_pdf": bool(state.get("cv")),
                        "letter_pdf": bool(state.get("letter")),
                    },
                    ensure_ascii=False,
                ),
                schema(
                    kind="string", text="string", scope="string", action_id="string"
                ),
                definitions,
                call,
                system_prompt=PREPARATION_PROMPT,
            )
            action = {"id": result["action_id"]}
            if (
                result["kind"] == "ready"
                and self.actions.get(action["id"], {}).get("phase") != "submit"
            ):
                raise ConnectorError("browsentic_submission_action_unknown")
            if result["kind"] == "challenge" and re.search(
                r"\bgoogle\b", result["text"], re.IGNORECASE
            ):
                await self.current_url(rpc, tab)
                page = self.json_result(
                    await self.use(rpc, "page_getPageInfo", {"maxPerKind": 100})
                )
                result = check_google_option(result, page)
            if result["kind"] in {"registration", "account_required"}:
                page = urlsplit(await self.current_url(rpc, tab))
                scope = f"{page.scheme}://{page.netloc}"
                if result["kind"] == "registration":
                    result = registration_result(
                        result, scope, memory, can_create=state["mode"] == "production"
                    )
                else:
                    result["scope"] = scope
            return {**result, "browser_tab": tab, "action": action}

    def fill(self, state, memory):
        try:
            return asyncio.run(self.fill_async(state, memory))
        except DocumentVerificationError as error:
            return {"kind": "challenge", "text": str(error), "scope": "dossier"}

    def run_account(self, state, memory):
        if state["mode"] != "production":
            return {
                "status": "failure",
                "cause": "account_creation_requires_production",
            }
        return asyncio.run(AccountAgent(self).run(state, memory, state["browser_tab"]))

    def run_form(self, state, memory):
        if state["mode"] != "production":
            raise ConnectorError("browsentic_direct_mode_invalid")
        try:
            return asyncio.run(self.native_with_receipt(state, memory))
        except DocumentVerificationError as error:
            # Le tour direct pouvait avoir agi avant de demander la pièce.
            # Réconcilier la tentative avant d’autoriser une nouvelle transmission.
            return {
                "kind": "unknown",
                "signal": "piece_incomplete",
                "stage": "piece",
                "piece": error.piece,
                "text": str(error),
                "transmission_attempted": False,
            }

    async def native_with_receipt(self, state, memory, *, verify=False):
        output = await self.agent_form(state, memory, verify=verify)
        receipt = output.get("receipt")
        if receipt and not await self.receipt_observed(
            output.get("browser_tab"), receipt, state["offer"]
        ):
            output.pop("receipt")
            output.update(kind="unknown", transmission_attempted=True)
        return output

    async def receipt_observed(self, tab, receipt, offer):
        if not tab or not receipt.get("evidence"):
            return False
        expected = urlsplit(receipt["url"])
        if (
            expected.scheme != "https"
            or not expected.hostname
            or expected.username
            or expected.password
        ):
            return False
        expected = expected._replace(query="", fragment="")
        try:
            async with (
                asyncio.timeout(12),
                Session(self.command, self.cwd, codex_environment()) as rpc,
            ):
                await self.connect(rpc)
                current = await self.current_url(rpc, tab)
                if urlsplit(current)._replace(query="", fragment="") != expected:
                    return False
                page = self.json_result(await self.use(rpc, "page_extractText", {}))
                text = page.get("text") or page.get("content") or ""
                proof = " ".join(receipt["evidence"].split())
                observed = " ".join(text.split())
                target = [offer.get("title"), offer.get("requisition")]
                if (
                    proof not in observed
                    or not any(
                        str(value).strip()
                        and " ".join(str(value).casefold().split())
                        in observed.casefold()
                        for value in target
                        if value is not None
                    )
                    or await self.current_url(rpc, tab) != current
                ):
                    return False
        except (ConnectorError, OSError, TimeoutError, ValueError):
            return False
        receipt["url"] = expected.geturl()
        return True

    async def agent_form(self, state, memory, verify=False):
        # App Server appelle directement le MCP. Le graphe lit le résultat du tour.
        documents = {piece: bool(state.get(piece)) for piece in ("cv", "letter")}

        async def document_call(name, args):
            try:
                if verify or name not in DOCUMENT_TOOL_NAMES:
                    raise ConnectorError("browsentic_action_denied")
                async with Session(
                    self.command, self.cwd, codex_environment()
                ) as session:
                    await self.connect(session)
                    value = await self.document_tool(session, state, name, args)
            except DocumentVerificationError:
                raise
            except ConnectorError as error:
                return {
                    "success": False,
                    "contentItems": [{"type": "inputText", "text": str(error)}],
                }
            return {
                "success": True,
                "contentItems": [{"type": "inputText", "text": value}],
            }

        context = {
            **dossier_context(state),
            "memory": memory,
            "browser_tab": state.get("browser_tab"),
            "account_result": state.get("account_result"),
            "account_operation": state.get("account_operation"),
            "documents": documents,
        }
        if verify:
            mandate = (
                "Vérifie uniquement si une candidature a déjà été déposée pour cette offre. "
                "Cherche un reçu visible ou l’offre précise dans l’historique du portail. "
                "Si la preuve manque, retourne unknown. Reste en lecture seule, "
                "n’entame aucun formulaire et ne déclenche aucun nouveau dépôt. Indique son onglet, "
                "ou 0 si inconnu. Pour submitted, renseigne confirmation_url avec la page "
                "HTTPS observée et evidence avec un court extrait textuel exact de la preuve, "
                "sans données privées. Renseigne sent_at uniquement pour un horodatage fiable avec fuseau."
            )
        else:
            mandate = state.get("_mandate_text") or SUBMISSION_MANDATE
        output = await self.codex.turn(
            "Données du dossier :\n" + json.dumps(context, ensure_ascii=False),
            AGENT_RESULT,
            tools=[] if verify else DOCUMENT_TOOLS,
            call=None if verify else document_call,
            mcp=(self.command, REVIEW_TOOLS if verify else FORM_TOOLS),
            system_prompt=mandate,
        )
        if not verify and output["kind"] in {"registration", "account_required"}:
            if output["browser_tab"] <= 0:
                return {**output, "kind": "blocked", "text": "account_tab_missing"}
            async with Session(self.command, self.cwd, codex_environment()) as rpc:
                await self.connect(rpc)
                current = urlsplit(await self.current_url(rpc, output["browser_tab"]))
            if (
                current.scheme != "https"
                or not current.hostname
                or current.username
                or current.password
            ):
                return {
                    **output,
                    "kind": "blocked",
                    "text": "portal_account_destination_unknown",
                }
            scope = f"{current.scheme}://{current.netloc}"
            operation = "registration" if output["kind"] == "registration" else "login"
            if operation == "registration":
                output = registration_result(output, scope, memory, can_create=True)
            output.update(scope=scope, account_operation=operation)
            if (
                output["kind"] in {"registration", "account_required"}
                and not output["transmission_attempted"]
            ):
                output["signal"] = "aucun"
        if output["browser_tab"] <= 0:
            output.pop("browser_tab")
        url = urlsplit(output["confirmation_url"])
        if (
            output["kind"] == "submitted"
            and output["evidence"].strip()
            and url.scheme == "https"
            and url.hostname
        ):
            output["receipt"] = {
                "url": output["confirmation_url"],
                "evidence": output["evidence"],
                "sent_at": output["sent_at"],
            }
        return output

    def obstacle_cleared(self, state, diagnostic):
        return asyncio.run(self.inspect_obstacle(state, diagnostic))

    async def inspect_obstacle(self, state, diagnostic):
        tab = state.get("browser_tab")
        if not tab or not diagnostic["portal"]:
            return False
        async with Session(self.command, self.cwd, codex_environment()) as rpc:
            await self.connect(rpc)
            try:
                url = await self.current_url(rpc, tab)
                if urlsplit(url).hostname != diagnostic["portal"]:
                    return False
                observed = await self.codex.turn(
                    "Lecture seule. Vérifie le poste et l’employeur visibles puis la condition "
                    "dans l’onglet actif. Retourne checked=true seulement en présence d’un "
                    "indice positif et attribuable à cette offre. Une affirmation de l’utilisateur "
                    "ou l’absence du message antérieur ne suffit pas. "
                    + json.dumps(
                        {
                            "title": state["offer"].get("title"),
                            "company": state["offer"].get("company"),
                            "condition": diagnostic["condition"],
                        },
                        ensure_ascii=False,
                    ),
                    schema(checked="boolean"),
                    mcp=(self.command, sorted(READ)),
                )
                return observed["checked"] and await self.current_url(rpc, tab) == url
            except ConnectorError:
                return False

    async def receipt(self, rpc, tab, state):
        url = await self.current_url(rpc, tab)
        for rule in self.verifications:
            if self.matches(url, rule):
                page = await self.use(
                    rpc,
                    "page_extractText",
                    {"maxLength": 8000, "target": {"selector": rule["selector"]}},
                )
                text = " ".join(item.get("text", "") for item in page["content"])
                if rule["marker"] in text and all(
                    state["offer"].get(key) and state["offer"][key] in text
                    for key in rule.get("offer_fields", ["title"])
                ):
                    return {"url": url, "marker": rule["marker"]}
        return None

    async def verify_async(self, state):
        async with (
            asyncio.timeout(60),
            Session(self.command, self.cwd, codex_environment()) as rpc,
        ):
            await self.connect(rpc)
            tab = self.tabs.get(state["dossier"], state.get("browser_tab"))
            if tab is not None:
                tabs = await self.inventory(rpc)
                if any(row.get("tabId") == tab for row in tabs.get("tabs", [])):
                    await self.use(rpc, "page_switchTab", {"tabId": tab})
                    result = await self.receipt(rpc, tab, state)
                    if result:
                        return result
            for rule in self.verifications:
                if rule.get("check_url"):
                    result = self.json_result(
                        await self.use(
                            rpc,
                            "page_openTab",
                            {
                                "url": rule["check_url"],
                                "active": True,
                            },
                        )
                    )
                    receipt = await self.receipt(rpc, result["tabId"], state)
                    if receipt:
                        return receipt
            return None

    def verify(self, state):
        if (state.get("submission") or {}).get("native"):
            result = asyncio.run(self.native_with_receipt(state, [], verify=True))
            return result.get("receipt")
        return asyncio.run(self.verify_async(state))
