"""Accès au compte du candidat dans l’espace employeur associé au dossier."""

import base64
import binascii
import json
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .codex import ConnectorError


def confirm_address(queue, mode, address):
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", address):
        raise ValueError("invalid_login_address")
    with queue.connect() as db:
        db.execute(
            """INSERT INTO applications.confirmed_addresses(candidate,mode,email)
               VALUES (%s,%s,%s) ON CONFLICT (candidate,mode) DO UPDATE
               SET email=excluded.email, confirmed_at=now()""",
            (queue.candidate, mode, address),
        )


class PortalAccounts:
    def __init__(self, queue, key_file, pages):
        self.queue = queue
        self.key_file = Path(key_file)
        self.pages = pages

    def cipher(self):
        try:
            key = base64.b64decode(self.key_file.read_bytes().strip(), validate=True)
            if len(key) != 32:
                raise ValueError()
            return AESGCM(key)
        except (ValueError, OSError, binascii.Error):
            raise ConnectorError("portal_account_key_unavailable") from None

    def credentials(self, dossier, url, decisions):
        origin = urlsplit(url)
        if (
            origin.scheme != "https"
            or not origin.hostname
            or origin.username
            or origin.password
        ):
            raise ConnectorError("portal_account_destination_unknown")
        provider = f"{origin.scheme}://{origin.netloc}"
        consent = [
            r.get("choice")
            for r in decisions
            if r.get("kind") == "registration" and r.get("scope") == provider
        ]
        with self.queue.connect() as db:
            target = db.execute(
                """SELECT candidate,mode,content->>'company' AS employer
                   FROM applications.dossiers WHERE id=%s AND candidate=%s""",
                (dossier, self.queue.candidate),
            ).fetchone()
            rules = [
                r
                for r in self.pages
                if target and r["url"] == url and r["employer"] == target["employer"]
            ]
            if len(rules) != 1 or not rules[0].get("space"):
                raise ConnectorError("portal_account_destination_unknown")
            scope = (target["candidate"], target["mode"], provider, rules[0]["space"])
            contact = db.execute(
                """SELECT email FROM applications.confirmed_addresses
                   WHERE candidate=%s AND mode=%s FOR SHARE""",
                scope[:2],
            ).fetchone()
            if not contact:
                raise ConnectorError("portal_account_address_unconfirmed")
            email = contact["email"]
            query = """SELECT id,login_email,encrypted_password,status
                       FROM applications.portal_accounts
                       WHERE candidate=%s AND mode=%s AND provider=%s AND employer_space=%s"""
            row = db.execute(query, scope).fetchone()
            if (consent and consent[-1] == "deny") or (
                not row and consent[-1:] != ["allow"]
            ):
                raise ConnectorError("portal_account_approval_required")
            cipher = self.cipher()
            aad = json.dumps((*scope, email), ensure_ascii=False).encode()
            if not row:
                nonce = os.urandom(12)
                password = secrets.token_urlsafe(30)
                encrypted = nonce + cipher.encrypt(nonce, password.encode(), aad)
                db.execute(
                    """INSERT INTO applications.portal_accounts
                       (id,candidate,mode,provider,employer_space,login_email,encrypted_password)
                       VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT
                       (candidate,mode,provider,employer_space) DO NOTHING""",
                    (uuid4(), *scope, email, encrypted),
                )
                row = db.execute(query, scope).fetchone()
            if row["login_email"] != email:
                raise ConnectorError("portal_account_address_changed")
            payload = bytes(row["encrypted_password"])
            try:
                password = cipher.decrypt(payload[:12], payload[12:], aad).decode()
            except (InvalidTag, ValueError):
                raise ConnectorError("portal_account_key_mismatch") from None
            db.execute(
                """INSERT INTO applications.dossier_portal_accounts VALUES (%s,%s)
                   ON CONFLICT DO NOTHING""",
                (dossier, row["id"]),
            )
        return email, password, row["status"]

    async def fill(self, browser, rpc, dossier, tab, decisions):
        url = await browser.current_url(rpc, tab)
        email, password, status = self.credentials(dossier, url, decisions)
        for field, value in (("email", email), ("password", password)):
            if await browser.current_url(rpc, tab) != url:
                raise ConnectorError("portal_account_destination_changed")
            await browser.use(
                rpc,
                "page_fillInput",
                {
                    "target": {"selector": f'input[type="{field}"]'},
                    "value": value,
                },
            )
        return status
