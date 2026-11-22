"""Deux arrivées Thunderbird inversées et reprise des checkpoints sur le seul loopback."""

import asyncio
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from uuid import uuid4

import psycopg
from linkedin_applications.browser import Browsentic
from linkedin_applications.codex import Session
from linkedin_applications.confirmations import EmailConfirmations, matching_notice
from linkedin_applications.postgres_queue import PostgresQueue
from linkedin_applications.runner import Runner

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "recette_browsentic"))
from thunderbird import prepare

ORIGIN = "https://portail.invalid"
FOLDER = "mailbox://nobody@Local%20Folders/Recette"
ADDRESS = "candidat@example.invalid"


@contextmanager
def mailbox(home, messages):
    profile = home / "profile"
    repo = Path(os.environ["THUNDERBIRD_MCP_REPO"])
    prepare(profile, repo / "dist/thunderbird-mcp.xpi", "", fixtures=messages)
    info = home / "thunderbird-mcp/connection.json"
    runtime = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "TMPDIR": str(home),
        "MOZ_HEADLESS": "1",
        "DBUS_SESSION_BUS_ADDRESS": "disabled:",
    }
    with subprocess.Popen(
        [os.environ["THUNDERBIRD"], "-no-remote", "-profile", profile, "-offline"],
        env=runtime,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ) as process:
        try:
            for _ in range(180):
                if info.is_file():
                    break
                if process.poll() is not None:
                    raise RuntimeError("Thunderbird de recette indisponible")
                time.sleep(0.5)
            else:
                raise RuntimeError("MCP Thunderbird indisponible")
            yield [
                "env",
                "THUNDERBIRD_MCP_CONNECTION_FILE=" + str(info),
                "node",
                str(repo / "mcp-bridge.cjs"),
            ]
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


class Portal(Browsentic):
    def __init__(self, directory):
        super().__init__(
            directory, [sys.executable, str(HERE / "portal.py"), str(directory)], {}
        )
        self.visits = {}
        self.root = directory

    def fill(self, state, memory):
        name = state["offer"]["company"]
        self.visits[name] = self.visits.get(name, 0) + 1
        if name == "C" or (self.root / (name + ".verified")).exists():
            return {"kind": "blocked", "text": "Suite du formulaire atteinte"}
        return {"kind": "account_confirmation", "browser_tab": ord(name) - 64}


def seed(directory):
    ids = {name: uuid4() for name in "ABC"}
    pdf = b"%PDF fixture"
    digest = hashlib.sha256(pdf).hexdigest()
    cv = directory / "fixture.pdf"
    cv.write_bytes(pdf)
    with psycopg.connect() as db:
        db.execute("CREATE ROLE recette LOGIN IN ROLE linkedin_applications")
        db.execute(
            "INSERT INTO documents.cv_versions VALUES (%s,%s,'cv de recette','fixture',DEFAULT)",
            (digest, pdf),
        )
        db.execute(
            """INSERT INTO discovery.cycles SELECT repeat('a',32),'now',sha256,'cv','p','p','{}','done' FROM documents.cv_versions"""
        )
        db.execute(
            "INSERT INTO applications.confirmed_addresses(candidate,mode,email) VALUES ('fixture','recipe',%s)",
            (ADDRESS,),
        )
        for name, dossier in ids.items():
            db.execute(
                "INSERT INTO discovery.versions(id,offer_key,content,canonical_url) VALUES (%s,%s,'{}',%s)",
                (name, name, ORIGIN + "/" + name),
            )
            db.execute(
                """INSERT INTO applications.dossiers(id,candidate,identity,mode,cycle_id,version_id,canonical_url,content,cv_sha256,uncertain)
                VALUES(%s,'fixture',%s,'recipe',repeat('a',32),%s,%s,'{}',%s,false)""",
                (dossier, name, name, ORIGIN + "/" + name, digest),
            )
            account = uuid4()
            db.execute(
                """INSERT INTO applications.portal_accounts(id,candidate,mode,provider,employer_space,login_email,encrypted_password)
                VALUES (%s,'fixture','recipe',%s,%s,%s,'fixture')""",
                (account, ORIGIN, name, ADDRESS),
            )
            db.execute(
                "INSERT INTO applications.dossier_portal_accounts VALUES (%s,%s)",
                (dossier, account),
            )
    return {
        name: {
            "dossier": str(dossier),
            "offer": {"company": name, "title": name},
            "version": name,
            "mode": "recipe",
            "cv": str(cv),
            "cv_hash": digest,
        }
        for name, dossier in ids.items()
    }


def main():
    if {
        row.split(":")[0].strip()
        for row in Path("/proc/net/dev").read_text().splitlines()[2:]
    } != {"lo"}:
        raise RuntimeError("loopback requis")
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        items = seed(home)
        queue = PostgresQueue(home, "dbname=postgres user=recette", "fixture")
        queue.items = lambda: list(items.values())
        portal = Portal(home)
        nonce = secrets.token_hex(6)
        rules = [
            {
                "provider": ORIGIN,
                "space": n,
                "subject": f"Confirmation {n} {nonce}",
                "sender": "portail@example.invalid",
                "folder": FOLDER,
                "confirmed_url": ORIGIN + "/" + n + "/actif",
                "confirmed_text": "Espace " + n + " actif",
            }
            for n in "AB"
        ]
        confirm = EmailConfirmations(queue, portal, ["/bin/false"], rules)
        portal.confirmations = confirm
        runner = Runner(queue, portal, None, None)
        try:
            for n in "AB":
                assert runner.run(items[n])["status"] == "waiting_account_confirmation"
            # Le transport est fermé. C peut effectuer son tour.
            assert runner.run(items["A"])["status"] == "waiting_account_confirmation"
            assert runner.run(items["C"])["reason"] == "Suite du formulaire atteinte"
        finally:
            runner.close()
        events = []
        tokens = {}
        now = datetime.now(UTC)
        for n in "BA":
            token = "G15-" + n + "-" + secrets.token_hex(6)
            tokens[n] = token
            events.append(
                "From: portail@example.invalid\r\nTo: "
                + ADDRESS
                + "\r\nSubject: Confirmation "
                + n
                + " "
                + nonce
                + "\r\nMessage-ID: <"
                + n
                + "."
                + nonce
                + "@example.invalid>\r\nDate: "
                + format_datetime(now)
                + "\r\n\r\n"
                + token
                + "\r\n"
            )
        runner = Runner(queue, portal, None, None)
        try:
            with mailbox(home, events) as command:
                confirm.command = command
                for n in "BA":
                    # Le pilote local de recette saisit uniquement son propre témoin synthétique.
                    for _ in range(20):
                        if asyncio.run(
                            verify_fixture_code(
                                portal, command, rules[ord(n) - 65], n, tokens[n]
                            )
                        ):
                            break
                        time.sleep(0.5)
                    else:
                        raise AssertionError("Message synthétique manquant")
                    assert (
                        runner.run(items[n])["reason"] == "Suite du formulaire atteinte"
                    )
                    if n == "B":
                        assert (
                            runner.run(items["A"])["status"]
                            == "waiting_account_confirmation"
                        )
        finally:
            runner.close()
        with queue.connect() as db:
            assert (
                db.execute(
                    "SELECT count(*) n FROM applications.email_challenges WHERE confirmed_at IS NOT NULL"
                ).fetchone()["n"]
                == 2
            )
            assert (
                db.execute(
                    "SELECT count(*) n FROM applications.portal_accounts WHERE status='actif'"
                ).fetchone()["n"]
                == 2
            )
            assert (
                db.execute(
                    "SELECT count(*) n FROM applications.submission_receipts"
                ).fetchone()["n"]
                == 0
            )
            rows = db.execute("""
                SELECT convert_to(checkpoint::text || metadata::text,'UTF8') AS payload FROM runtime_g2.checkpoints
                UNION ALL SELECT blob FROM runtime_g2.checkpoint_blobs WHERE blob IS NOT NULL
                UNION ALL SELECT blob FROM runtime_g2.checkpoint_writes
            """).fetchall()
            assert rows and all(
                token.encode() not in row["payload"]
                for row in rows
                for token in tokens.values()
            )
        assert not (home / "checkpoints.sqlite3").exists()
        assert all(portal.visits[n] == 2 for n in "AB")
        print(
            "Deux messages Thunderbird en ordre inverse, deux reprises, panne isolée, zéro reçu et checkpoints expurgés."
        )


async def verify_fixture_code(portal, command, rule, space, expected):
    # Réservé aux EML écrits ci-dessus et au profil Thunderbird sans réseau.
    async with Session(command, portal.cwd) as rpc:
        await portal.connect(rpc)

        async def call(tool, **args):
            reply = await rpc.request("tools/call", {"name": tool, "arguments": args})
            if reply.get("isError"):
                return None
            return json.loads(reply["content"][0]["text"])

        rows = await call("searchMessages", query="subject:" + rule["subject"])
        if not isinstance(rows, list):
            return False
        rows = [r for r in rows if r.get("subject") == rule["subject"]]
        if len(rows) != 1:
            return False
        row = rows[0]
        assert row["subject"] == rule["subject"]
        assert isinstance(row["folderPath"], str) and row["folderPath"]
        rule["folder"] = row["folderPath"]
        check = {
            "login_email": ADDRESS,
            "started_at": datetime.now(UTC) - timedelta(minutes=3),
        }
        assert matching_notice([row], rule, check)
        assert matching_notice([row, row], rule, check) is None
        for changed in (
            {"recipients": "autre@example.invalid"},
            {"author": "autre@example.invalid"},
            {"date": "2000-01-01T00:00:00Z"},
            {"folderPath": "autre"},
            {"subject": rule["subject"] + " autre"},
        ):
            assert matching_notice([{**row, **changed}], rule, check) is None
        message = await call(
            "getMessage",
            folderPath=rule["folder"],
            messageId=row["id"],
            bodyFormat="text",
        )
        body = message["body"].strip()
        if body != expected:
            return False
        await asyncio.to_thread(
            subprocess.run,
            ["node", HERE / "verify.cjs"],
            input=json.dumps(
                {
                    "space": space,
                    "token": body,
                    "digest": hashlib.sha256(expected.encode()).hexdigest(),
                }
            )
            + "\n",
            text=True,
            check=True,
            timeout=45,
        )
        # Le formulaire du portail synthétique a validé le témoin dans Chrome.
        (portal.root / (space + ".verified")).touch()
        return True


if __name__ == "__main__":
    main()
