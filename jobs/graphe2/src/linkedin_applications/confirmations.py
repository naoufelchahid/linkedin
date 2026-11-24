"""Rapprochement d'une notification Thunderbird et de l’état observé du portail."""

import asyncio
import json
import re
from datetime import UTC, datetime
from email.utils import getaddresses
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .codex import ConnectorError, Session, codex_environment


def origin(url):
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        return None
    return f"https://{parts.netloc}"


def matching_notice(rows, rule, account):
    # Une page tronquée pourrait masquer un second message correspondant.
    if not isinstance(rows, list):
        return None
    matches = []
    now = datetime.now(UTC)
    for row in rows:
        if (
            row.get("folderPath") != rule["folder"]
            or row.get("subject") != rule["subject"]
        ):
            continue
        sender = getaddresses([row.get("author", "")])
        recipient = getaddresses([row.get("recipients", "")])
        if [a.lower() for _, a in sender] != [rule["sender"].lower()] or [
            a.lower() for _, a in recipient
        ] != [account["login_email"].lower()]:
            continue
        dated = datetime.fromisoformat(row["date"])
        if dated.tzinfo and account["started_at"] <= dated <= now and row.get("id"):
            matches.append(row["id"])
    if len(matches) == 1:
        return matches[0]
    return None


def activation_payload(body, activation, provider):
    """Retourne une seule preuve correspondant à la politique du portail."""
    if activation["kind"] == "code":
        matches = re.findall(activation["pattern"], body)
        codes = {
            value
            for value in matches
            if isinstance(value, str) and re.fullmatch(r"[0-9]{4,10}", value)
        }
        return next(iter(codes)) if len(codes) == 1 else None

    links = set()
    for candidate in re.findall(r'https://[^\s<>"\']+', body):
        parsed = urlsplit(candidate)
        query = parse_qs(parsed.query, keep_blank_values=True)
        key = activation["token_parameter"]
        if (
            origin(candidate) == provider
            and parsed.path == activation["link_path"]
            and not parsed.fragment
            and set(query) == {key}
            and len(query[key]) == 1
            and re.fullmatch(r"[A-Za-z0-9_.~-]{12,512}", query[key][0])
        ):
            links.add(candidate)
    return next(iter(links)) if len(links) == 1 else None


class EmailConfirmations:
    def __init__(self, queue, browser, thunderbird, rules, *, offline_recipe=False):
        self.queue = queue
        self.browser = browser
        self.command = thunderbird
        self.rules = rules
        self.offline_recipe = offline_recipe

    def rule(self, account):
        rules = [
            r
            for r in self.rules
            if r["provider"] == account["provider"]
            and r["space"] == account["employer_space"]
        ]
        if len(rules) != 1:
            return None
        rule = rules[0]
        if (
            not rule["confirmed_text"].strip()
            or origin(rule["confirmed_url"]) != account["provider"]
        ):
            return None
        # Un objet commun à deux espaces du même expéditeur ne distingue pas les comptes.
        key = ("folder", "sender", "subject")
        if sum(all(r[k] == rule[k] for k in key) for r in self.rules) != 1:
            return None
        return rule

    def begin(self, dossier, tab, *, waiting_url=None, provider=None):
        if not isinstance(tab, int) or tab <= 0:
            return False
        with self.queue.connect() as db:
            accounts = db.execute(
                """
                SELECT a.* FROM applications.dossier_portal_accounts d
                JOIN applications.portal_accounts a ON a.id=d.account_id
                WHERE d.dossier_id=%s AND a.candidate=%s
                  AND (%s::text IS NULL OR a.provider=%s)
            """,
                (dossier, self.queue.candidate, provider, provider),
            ).fetchall()
            if len(accounts) != 1:
                return False
            account = accounts[0]
            rule = self.rule(account)
            if not rule or (
                waiting_url is not None
                and waiting_url != rule.get("activation", {}).get("page_url")
            ):
                return False
            db.execute(
                """
                INSERT INTO applications.email_challenges(dossier_id,account_id,started_at,browser_tab)
                VALUES (%s,%s,date_trunc('second',%s::timestamptz),%s) ON CONFLICT DO NOTHING
            """,
                (
                    dossier,
                    account["id"],
                    account.get("registration_dispatched_at") or account["created_at"],
                    tab,
                ),
            )
            challenge = db.execute(
                "SELECT account_id,browser_tab FROM applications.email_challenges WHERE dossier_id=%s",
                (dossier,),
            ).fetchone()
            if (
                not challenge
                or challenge["account_id"] != account["id"]
                or challenge["browser_tab"] != tab
            ):
                return False
            db.execute(
                """UPDATE applications.portal_accounts SET status='confirmation_en_attente'
                WHERE id=%s AND status='creation_en_cours'""",
                (account["id"],),
            )
            return True

    async def apply_fixture_marker(self, mail, portal, account, rule, message_id):
        """Seuls les deux formulaires synthétiques dans le réseau loopback de recette."""
        space = account["employer_space"]
        interfaces = {
            row.split(":")[0].strip()
            for row in Path("/proc/net/dev").read_text().splitlines()[2:]
        }
        if (
            not self.offline_recipe
            or interfaces != {"lo"}
            or space not in {"A", "B"}
            or account["provider"] != "https://portail.invalid"
            or rule["sender"] != "portail@example.invalid"
            or account["login_email"] != "candidat@example.invalid"
            or rule["confirmed_url"] != f"https://portail.invalid/{space}/actif"
        ):
            return
        target = f"https://portail.invalid/{space}/confirmation"
        tab = account["browser_tab"]
        if await self.browser.current_url(portal, tab) != target:
            return
        reply = await mail.request(
            "tools/call",
            {
                "name": "getMessage",
                "arguments": {
                    "folderPath": rule["folder"],
                    "messageId": message_id,
                    "bodyFormat": "text",
                },
            },
        )
        if reply.get("isError"):
            return
        marker = json.loads(reply["content"][0]["text"])["body"].strip()
        if not re.fullmatch(r"G15-" + space + r"-[0-9a-f]{12}", marker):
            return
        if await self.browser.current_url(portal, tab) != target:
            return
        await self.browser.use(
            portal, "page_fillInput", {"target": {"selector": "#code"}, "value": marker}
        )
        if await self.browser.current_url(portal, tab) != target:
            return
        await self.browser.use(
            portal,
            "page_clickElement",
            {"target": {"selector": "button[data-confirm-registration]"}},
        )

    def claim_activation(self, dossier, digest):
        with self.queue.connect() as db:
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (digest,)
            )
            row = db.execute(
                """UPDATE applications.email_challenges c SET activation_message_sha256=%s
                WHERE c.dossier_id=%s AND c.confirmed_at IS NULL
                  AND c.activation_message_sha256 IS NULL
                  AND NOT EXISTS (SELECT FROM applications.email_challenges other
                    WHERE other.activation_message_sha256=%s OR other.matched_message_sha256=%s)
                RETURNING dossier_id""",
                (digest, dossier, digest, digest),
            ).fetchone()
        return row is not None

    async def apply_activation(
        self, mail, portal, account, rule, message_id, *, observed_selector=None
    ):
        activation = rule.get("activation")
        if not activation or activation.get("kind") not in {"code", "link"}:
            return
        tab = account["browser_tab"]
        target = activation["page_url"]
        provider = account["provider"]
        if (
            origin(target) != provider
            or await self.browser.current_url(portal, tab) != target
        ):
            return
        reply = await mail.request(
            "tools/call",
            {
                "name": "getMessage",
                "arguments": {
                    "folderPath": rule["folder"],
                    "messageId": message_id,
                    "bodyFormat": "text",
                },
            },
        )
        if reply.get("isError"):
            return
        body = json.loads(reply["content"][0]["text"])["body"]
        if not isinstance(body, str) or len(body) > 100_000:
            return
        value = activation_payload(body, activation, provider)
        if not value or await self.browser.current_url(portal, tab) != target:
            return
        if observed_selector is not None and activation["kind"] == "code":
            page = self.browser.json_result(
                await self.browser.use(portal, "page_getPageInfo", {"maxPerKind": 100})
            )
            fields = [
                field
                for field in page.get("interactive", {}).get("fields", [])
                if field.get("selector") == observed_selector
                and field.get("tag") == "input"
                and not field.get("state", {}).get("disabled")
            ]
            if not observed_selector or len(fields) != 1:
                return None
        digest = sha256(message_id.encode()).hexdigest()
        if not self.claim_activation(account["dossier_id"], digest):
            return
        if await self.browser.current_url(portal, tab) != target:
            return
        if activation["kind"] == "link":
            await self.browser.use(portal, "page_navigate", {"url": value})
            return "link_opened"
        else:
            await self.browser.use(
                portal,
                "page_fillInput",
                {
                    "target": {
                        "selector": (
                            activation["code_selector"]
                            if observed_selector is None
                            else observed_selector
                        )
                    },
                    "value": value,
                },
            )
            if observed_selector is not None:
                return "code_filled"
            if await self.browser.current_url(portal, tab) == target:
                await self.browser.use(
                    portal,
                    "page_clickElement",
                    {
                        "target": {
                            "selector": activation["confirm_selector"],
                            "text": activation["confirm_text"],
                        }
                    },
                )

    @staticmethod
    async def search_notice(mail, account, rule):
        reply = await mail.request(
            "tools/call",
            {
                "name": "searchMessages",
                "arguments": {
                    "folderPath": rule["folder"],
                    "query": "subject:" + rule["subject"],
                    "startDate": account["started_at"].isoformat(),
                    "includeSubfolders": False,
                },
            },
        )
        if reply.get("isError"):
            return None
        return matching_notice(json.loads(reply["content"][0]["text"]), rule, account)

    async def activation_for_agent(self, dossier, provider, tab, url, selector):
        if not self.begin(dossier, tab, waiting_url=url, provider=provider):
            return None
        account = self.challenge(dossier)
        if (
            not account
            or account["provider"] != provider
            or account["browser_tab"] != tab
        ):
            return None
        rule = self.rule(account)
        if not rule:
            return None
        async with (
            asyncio.timeout(12),
            Session(self.command, self.browser.cwd, codex_environment()) as mail,
            Session(
                self.browser.command, self.browser.cwd, codex_environment()
            ) as portal,
        ):
            await self.browser.connect(mail)
            await self.browser.connect(portal)
            message_id = await self.search_notice(mail, account, rule)
            if message_id:
                return await self.apply_activation(
                    mail,
                    portal,
                    account,
                    rule,
                    message_id,
                    observed_selector=selector,
                )
        return None

    async def validate_agent_code(self, rpc, dossier, provider, tab, url, selector):
        account = self.challenge(dossier)
        if (
            not account
            or account["provider"] != provider
            or account["browser_tab"] != tab
            or account["confirmed_at"]
            or not account.get("activation_message_sha256")
        ):
            return False
        rule = self.rule(account)
        activation = rule.get("activation", {}) if rule else {}
        if activation.get("kind") != "code" or url != activation.get("page_url"):
            return False
        page = self.browser.json_result(
            await self.browser.use(rpc, "page_getPageInfo", {"maxPerKind": 100})
        )
        buttons = [
            button
            for button in page.get("interactive", {}).get("buttons", [])
            if button.get("selector") == selector
            and not button.get("state", {}).get("disabled")
        ]
        if len(buttons) != 1 or await self.browser.current_url(rpc, tab) != url:
            return False
        await self.browser.use(
            rpc, "page_clickElement", {"target": {"selector": selector}}
        )
        return True

    async def observe(self, account, rule):
        async with asyncio.timeout(45 if self.offline_recipe else 8):
            async with Session(
                self.command, self.browser.cwd, codex_environment()
            ) as mail:
                await self.browser.connect(mail)
                message_id = await self.search_notice(mail, account, rule)
                if not message_id:
                    return None
                browser = self.browser
                async with Session(
                    browser.command, browser.cwd, codex_environment()
                ) as portal:
                    await browser.connect(portal)
                    tab = account["browser_tab"]
                    await browser.use(portal, "page_switchTab", {"tabId": tab})
                    if await browser.current_url(portal, tab) != rule["confirmed_url"]:
                        if self.offline_recipe:
                            await self.apply_fixture_marker(
                                mail, portal, account, rule, message_id
                            )
                        else:
                            await self.apply_activation(
                                mail, portal, account, rule, message_id
                            )
                    if await browser.current_url(portal, tab) != rule["confirmed_url"]:
                        return None
                    page = browser.json_result(
                        await browser.use(portal, "page_extractText", {})
                    )
                    content = page.get("text") or page.get("content") or ""
                    if (
                        rule["confirmed_text"] not in content
                        or account["login_email"].casefold()
                        not in content.casefold().split()
                        or await browser.current_url(portal, tab)
                        != rule["confirmed_url"]
                    ):
                        return None
                    return sha256(message_id.encode()).hexdigest()

    def challenge(self, dossier):
        with self.queue.connect() as db:
            return db.execute(
                """
                SELECT c.*,a.provider,a.employer_space,a.login_email,a.status
                FROM applications.email_challenges c JOIN applications.portal_accounts a ON a.id=c.account_id
                WHERE c.dossier_id=%s AND a.candidate=%s
            """,
                (dossier, self.queue.candidate),
            ).fetchone()

    def poll(self, dossier):
        account = self.challenge(dossier)
        if not account:
            return False
        if account["confirmed_at"]:
            return True
        rule = self.rule(account)
        if not rule:
            return False
        try:
            digest = asyncio.run(self.observe(account, rule))
        except (
            OSError,
            TimeoutError,
            ConnectorError,
            KeyError,
            ValueError,
            TypeError,
            re.error,
        ):
            return False
        if not digest:
            return False
        with self.queue.connect() as db:
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (digest,)
            )
            other = db.execute(
                """SELECT dossier_id FROM applications.email_challenges
                WHERE matched_message_sha256=%s OR to_jsonb(email_challenges)->>'activation_message_sha256'=%s""",
                (digest, digest),
            ).fetchone()
            if other and str(other["dossier_id"]) != str(dossier):
                return False
            db.execute(
                """UPDATE applications.email_challenges SET matched_message_sha256=%s,confirmed_at=now()
                WHERE dossier_id=%s AND confirmed_at IS NULL""",
                (digest, dossier),
            )
            db.execute(
                """UPDATE applications.portal_accounts SET status='actif' WHERE id=%s""",
                (account["account_id"],),
            )
        return True
