"""Expose à Codex les opérations Browsentic autorisées pour le formulaire courant."""

import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .codex import Codex, ConnectorError, Session, codex_environment
from .graph import fingerprint
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
    "page_listFiles",
    "page_attachFile",
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
)
AGENT_RESULT["properties"]["kind"]["enum"] = [
    "submitted",
    "unknown",
    "blocked",
    "question",
    "letter",
    "registration",
    "challenge",
]


class Browsentic:
    # Ce MCP cible l’onglet actif. Pendant une intervention, le worker préserve le focus.
    background_safe = False
    native_submission = True

    def __init__(self, data, command, policy):
        self.cwd = Path(data) / "browser"
        self.codex = Codex(self.cwd)
        self.command = command
        self.actions = policy.get("actions", {})
        self.verifications = policy.get("verification", [])
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

    def attachment(self, path):
        entry = self.files.get(fingerprint(path)) if path else None
        if isinstance(entry, str) and entry:
            return {"fileId": entry}
        if (
            isinstance(entry, dict)
            and isinstance(entry.get("downloadId"), str)
            and entry["downloadId"]
        ):
            return {"downloadId": entry["downloadId"]}
        return {}

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
            reference = self.attachment(state.get(rule["piece"]))
            if not reference:
                raise ConnectorError("browsentic_attachment_not_registered")
            args.update(reference)
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
        documents = {}
        if not verify:
            for piece in ("cv", "letter"):
                if path := state.get(piece):
                    documents[piece] = {
                        "name": Path(path).name,
                        "attachment": self.attachment(path),
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
                "n’entame aucun formulaire et ne déclenche aucun nouveau dépôt."
            )
        else:
            mandate = (
                "Prends en charge dans le navigateur tout le formulaire de cette offre, jusqu’à "
                "sa validation et son dépôt. Choisis toi-même les champs et gestes d’après la page "
                "et utilise les outils Browsentic directement. Suis les liens de candidature "
                "propres à cette offre. Pour un formulaire intégré, inspecte frames dans "
                "page_getPageInfo puis entre avec page_switchFrame({frame:{selector:...}}). "
                "Réutilise les faits confirmés du dossier. Renseigne les champs et coche les "
                "options dont la réponse est confirmée. Laisse vides les options facultatives "
                "sans réponse confirmée. Pour un fait manquant indispensable, retourne question. "
                "Pour un compte obligatoire sans décision applicable au portail, retourne "
                "registration avec l’origine exacte. Pour une vérification humaine, un code "
                "ou un consentement non confirmé retourne challenge. Pour une lettre requise "
                "retourne letter. Pour joindre un PDF, utilise fileId ou downloadId selon la "
                "référence Browsentic du document. Si la référence manque, retourne challenge "
                "en précisant quelle pièce doit être associée. En cas de refus d’un outil, respecte le refus. "
                "Transmets au plus une fois. Dès le premier geste pouvant transmettre, indique "
                "transmission_attempted=true même si sa réponse se perd. Observe le résultat "
                "et retourne submitted uniquement si une preuve identifie le dépôt de cette offre. "
                "Si le sort du geste est inconnu retourne unknown. Pour une attente précise qui "
                "survient avant toute transmission indique transmission_attempted=false."
            )
        output = await self.codex.turn(
            mandate
            + "\nReprends l’onglet du dossier si identifiable, sinon ouvre la page LinkedIn "
            "de l’offre. Retourne l’identifiant numérique de l’onglet, ou 0 s’il est inconnu. "
            "La preuve doit décrire ce que tu as observé, sans données d’authentification. "
            "Renseigne sent_at seulement si le portail affiche une heure fiable avec fuseau. "
            "Données du dossier :\n" + json.dumps(context, ensure_ascii=False),
            AGENT_RESULT,
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
