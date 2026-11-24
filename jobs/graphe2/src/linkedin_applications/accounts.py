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


def registration_decision(memory, provider, *, permanent=False):
    """Conserve une exclusion explicite, puis applique l’accord permanent du candidat."""
    return next(
        (
            row["choice"]
            for row in reversed(memory)
            if row["kind"] == "registration" and row["scope"] == provider
        ),
        "allow" if permanent else None,
    )


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

    def credentials(self, dossier, url, decisions, *, native=False, create=True):
        origin = urlsplit(url)
        if (
            origin.scheme != "https"
            or not origin.hostname
            or origin.username
            or origin.password
        ):
            raise ConnectorError("portal_account_destination_unknown")
        provider = f"{origin.scheme}://{origin.netloc}"
        consent = registration_decision(decisions, provider, permanent=native)
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
            if not target or not target["employer"] or len(rules) > 1:
                raise ConnectorError("portal_account_destination_unknown")
            if rules:
                space = rules[0].get("space")
            elif native:
                # Retrouve d’abord l’espace déjà lié, pour garder sa clé et son chiffrement.
                linked = db.execute(
                    """SELECT a.employer_space FROM applications.portal_accounts a
                       JOIN applications.dossier_portal_accounts d ON d.account_id=a.id
                       WHERE d.dossier_id=%s AND a.candidate=%s AND a.provider=%s""",
                    (dossier, self.queue.candidate, provider),
                ).fetchall()
                if len(linked) > 1:
                    raise ConnectorError("portal_account_ambiguous")
                spaces = {
                    p["space"]
                    for p in self.pages
                    if p.get("space")
                    and p.get("employer") == target["employer"]
                    and urlsplit(p["url"]).netloc == origin.netloc
                }
                if not linked and len(spaces) > 1:
                    raise ConnectorError("portal_account_ambiguous")
                space = (
                    linked[0]["employer_space"]
                    if linked
                    else next(
                        iter(spaces),
                        "employer:" + " ".join(target["employer"].casefold().split()),
                    )
                )
            else:
                space = None
            if not space:
                raise ConnectorError("portal_account_destination_unknown")
            scope = (target["candidate"], target["mode"], provider, space)
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
            if consent == "deny" or (not row and (not create or consent != "allow")):
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

    def claim_registration(self, dossier, provider):
        return self.update_linked(
            dossier,
            provider,
            "registration_dispatched_at=now()",
            "AND a.status='creation_en_cours' AND a.registration_dispatched_at IS NULL",
        )

    def mark_active(self, dossier, provider):
        return self.update_linked(dossier, provider, "status='actif'")

    def update_linked(self, dossier, provider, assignment, condition=""):
        # Les deux appels ci-dessus fournissent des expressions SQL constantes.
        with self.queue.connect() as db:
            rows = db.execute(
                """SELECT a.id FROM applications.portal_accounts a
                    JOIN applications.dossier_portal_accounts d ON d.account_id=a.id
                    WHERE d.dossier_id=%s AND a.candidate=%s AND a.provider=%s
                    FOR UPDATE OF a""",
                (dossier, self.queue.candidate, provider),
            ).fetchall()
            if len(rows) != 1:
                return False
            return (
                db.execute(
                    "UPDATE applications.portal_accounts AS a SET "
                    + assignment
                    + " WHERE a.id=%s "
                    + condition,
                    (rows[0]["id"],),
                ).rowcount
                == 1
            )

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
