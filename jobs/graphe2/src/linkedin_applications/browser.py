"""Expose à Codex les opérations Browsentic autorisées pour le formulaire courant."""

import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .codex import Codex, ConnectorError, Session, codex_environment
from .graph import fingerprint
from .mandate import TEXT as SUBMISSION_MANDATE
from .obstacles import SIGNALS, STAGES
from .urls import offer_url
from .writer import dossier_context, schema

READ = {"page_getPageInfo", "page_extractText"}
PREPARATION = {
    "page_clickElement",
    "page_fillInput",
    "page_selectOption",
    "page_attachFile",
    "page_navigate",
}
TRANSMISSION = {"page_clickElement", "page_trustedClick"}

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
]


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
            raise ConnectorError(f"browsentic_{piece}_missing")
        if not digest or digest != fingerprint(path):
            raise ConnectorError(f"browsentic_{piece}_integrity")
        files = self.files
        if self.policy_path is not None:
            try:
                files = json.loads(self.policy_path.read_text()).get("files", {})
            except (OSError, ValueError):
                raise ConnectorError(
                    f"browsentic_{piece}_registry_unavailable"
                ) from None
        entry = files.get(digest)
        if isinstance(entry, str):
            entry = {"fileId": entry}
        if not isinstance(entry, dict):
            raise ConnectorError(f"browsentic_{piece}_not_registered")
        if entry.get("fileId"):
            key, tool, rows = "fileId", "page_listFiles", "files"
        elif entry.get("downloadId"):
            key, tool, rows = "downloadId", "page_listDownloads", "downloads"
        else:
            raise ConnectorError(f"browsentic_{piece}_not_registered")
        if await self.current_url(rpc, tab) != url:
            raise ConnectorError("browsentic_destination_changed")
        inventory = self.json_result(await self.use(rpc, tool, {}))
        if not any(
            row.get("id") == entry[key] and row.get("size") == path.stat().st_size
            for row in inventory.get(rows, [])
        ):
            raise ConnectorError(f"browsentic_{piece}_reference_expired")
        if await self.current_url(rpc, tab) != url:
            raise ConnectorError("browsentic_destination_changed")
        return await self.use(
            rpc, "page_attachFile", {key: entry[key], "target": target}
        )

    async def perform(self, rpc, tab, state, name, value=None, phase="prepare"):
        rule = self.actions.get(name, {})
        legal = TRANSMISSION if phase == "submit" else PREPARATION
        if rule.get("phase") != phase or rule.get("tool") not in legal:
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
                        if phase not in {"prepare", "register"}:
                            raise ConnectorError("browsentic_action_denied")
                        if phase == "register" and not any(
                            row["kind"] == "registration"
                            and row["scope"] == rule["origin"]
                            and row["choice"] == "allow"
                            for row in memory
                        ):
                            raise ConnectorError(
                                "browsentic_registration_approval_required"
                            )
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
                            after = await self.inventory(rpc)
                            target = after.get("activeTabId")
                            if target != tab and target not in before:
                                target_url = urlsplit(
                                    await self.current_url(rpc, target)
                                )
                                origin = f"{target_url.scheme}://{target_url.netloc}"
                                if origin not in rule.get("destination_origins", []):
                                    raise ConnectorError(
                                        "browsentic_destination_unknown"
                                    )
                                tab = self.tabs[state["dossier"]] = target
                    elif name in READ:
                        result = await self.use(rpc, name, params)
                    else:
                        raise ConnectorError("browsentic_action_denied")
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
                "Suis le formulaire avec les outils proposés. Renseigne uniquement des faits confirmés "
                "et applicables. Pour un fait manquant retourne question, pour CAPTCHA ou code challenge, "
                "pour une inscription nécessaire registration, pour une lettre demandée letter, "
                "ou blocked si un prérequis empêche la suite. Retourne ready seulement au prochain "
                "geste de transmission vérifié, avec son identifiant action_id. "
                "Si le formulaire exige une pièce et qu’aucune action de préparation ne permet de "
                "joindre le fichier exact du cycle, retourne challenge et précise la pièce nécessaire. "
                "Si le portail exige un consentement et que la décision du candidat manque, retourne "
                "question en citant la case concernée. Si une autre action manque, retourne blocked. "
                "Pour registration, scope doit être l’origine HTTPS exacte du portail. Pour une réponse "
                "universelle, scope vaut global. Pour une réponse liée à l’employeur, scope prend la forme "
                "company:Nom exact. Pour les autres, indique le pays, le contrat ou le dossier concerné.\n"
                + json.dumps(
                    {
                        **dossier_context(state),
                        "memory": memory,
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
            )
            if (
                result["kind"] == "ready"
                and self.actions.get(result["action_id"], {}).get("phase") != "submit"
            ):
                raise ConnectorError("browsentic_submission_action_unknown")
            if result["kind"] == "registration":
                page = urlsplit(await self.current_url(rpc, tab))
                scope = f"{page.scheme}://{page.netloc}"
                result["scope"] = scope
                if any(
                    row["kind"] == "registration" and row["scope"] == scope
                    for row in memory
                ):
                    result.update(
                        kind="blocked",
                        text="Décision d’inscription déjà enregistrée pour ce portail.",
                    )
            return {**result, "browser_tab": tab, "action": {"id": result["action_id"]}}

    def fill(self, state, memory):
        return asyncio.run(self.fill_async(state, memory))

    def run_form(self, state, memory):
        if state["mode"] != "production":
            raise ConnectorError("browsentic_direct_mode_invalid")
        return asyncio.run(self.agent_form(state, memory))

    async def agent_form(self, state, memory, verify=False):
        # App Server appelle directement le MCP. Le graphe lit le résultat du tour.
        documents = {piece: bool(state.get(piece)) for piece in ("cv", "letter")}
        attach_tool = {
            "name": "attach_dossier_document",
            "description": "Joindre le CV ou la lettre figée au champ observé dans l’onglet actif.",
            "inputSchema": schema(
                piece="string", tab="integer", url="string", selector="string"
            ),
        }

        account_tool = {
            "name": "fill_portal_account",
            "description": "Renseigner le compte du candidat dans la page de connexion ou d’inscription reconnue. Retourne son état.",
            "inputSchema": schema(tab="integer"),
        }
        tools = [attach_tool]
        if self.accounts:
            tools.append(account_tool)

        async def attach(name, args):
            try:
                if verify or name not in {tool["name"] for tool in tools}:
                    raise ConnectorError("browsentic_action_denied")
                async with Session(
                    self.command, self.cwd, codex_environment()
                ) as session:
                    await self.connect(session)
                    if name == account_tool["name"]:
                        status = await self.accounts.fill(
                            self, session, state["dossier"], args["tab"], memory
                        )
                        return {
                            "success": True,
                            "contentItems": [
                                {"type": "inputText", "text": "Compte : " + status}
                            ],
                        }
                    await self.attach_document(
                        session,
                        args["tab"],
                        args["url"],
                        state,
                        args["piece"],
                        {"selector": args["selector"]},
                    )
            except ConnectorError as error:
                return {
                    "success": False,
                    "contentItems": [{"type": "inputText", "text": str(error)}],
                }
            return {
                "success": True,
                "contentItems": [{"type": "inputText", "text": "Pièce jointe."}],
            }

        context = {
            **dossier_context(state),
            "memory": memory,
            "browser_tab": state.get("browser_tab"),
            "documents": documents,
        }
        if verify:
            mandate = (
                "Vérifie uniquement si une candidature a déjà été déposée pour cette offre. "
                "Cherche un reçu visible ou l’offre précise dans l’historique du portail. "
                "Si la preuve manque, retourne unknown. Reste en lecture seule, "
                "n’entame aucun formulaire et ne déclenche aucun nouveau dépôt. Indique son onglet, "
                "ou 0 si inconnu, et une observation expurgée. Renseigne sent_at uniquement "
                "pour un horodatage affiché fiable avec fuseau."
            )
        else:
            mandate = state.get("_mandate_text") or SUBMISSION_MANDATE
        output = await self.codex.turn(
            mandate
            + "\nDonnées du dossier :\n"
            + json.dumps(context, ensure_ascii=False),
            AGENT_RESULT,
            tools=[] if verify else tools,
            call=None if verify else attach,
            mcp=(self.command, REVIEW_TOOLS if verify else FORM_TOOLS),
        )
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

    async def submit_async(self, state):
        async with (
            asyncio.timeout(60),
            Session(self.command, self.cwd, codex_environment()) as rpc,
        ):
            await self.connect(rpc)
            tab = self.tabs.get(state["dossier"])
            if tab is None:
                return None
            await self.perform(
                rpc, tab, state, state["planned_action"]["id"], phase="submit"
            )
            return await self.receipt(rpc, tab, state)

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

    def submit(self, state, attempt):
        return asyncio.run(self.submit_async(state))

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
            result = asyncio.run(self.agent_form(state, [], verify=True))
            return result.get("receipt")
        return asyncio.run(self.verify_async(state))
