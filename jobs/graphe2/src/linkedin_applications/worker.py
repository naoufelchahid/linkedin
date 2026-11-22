"""Le tableau lance ce processus local, qui conserve la file entre redémarrages."""

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from dotenv import dotenv_values

from .browser import Browsentic
from .connectors import ACTIONS, RESPONSE_ACTIONS, Mail, Telegram, private_write
from .legacy_selection import retained_rows
from .runner import Runner, config
from .storage import Queue, database, selected
from .writer import Writer


class Worker:
    def __init__(self, queue, runner, telegram):
        self.queue, self.runner, self.telegram = queue, runner, telegram
        self.recheck_at = 0
        self.path = queue.data / "telegram.json"
        self.telegram_state = (
            json.loads(self.path.read_text())
            if self.path.exists()
            else {
                "offset": 0,
                "prompts": {},
                "staged": {},
            }
        )

    def save(self):
        private_write(self.path, json.dumps(self.telegram_state, ensure_ascii=False))

    def pending(self):
        return {
            snap.values["question"]["id"]: snap.values
            for snap in self.runner.snapshots()
            if snap.interrupts
        }

    def notify(self, pending):
        for ident, dossier in pending.items():
            if ident in self.telegram_state["prompts"]:
                continue
            q = dossier["question"]
            title = dossier["offer"]["title"]
            text = f"{title}\n{q['text']}"
            if q["kind"] == "question":
                msg = self.telegram.text(text, reply_markup={"force_reply": True})
            else:
                if q["kind"] in {"mail", "recipe_mail"}:
                    draft = dossier["draft"]
                    text = f"{title}\nÀ {draft['recipient']}\n{draft['subject']}\n\n{draft['body']}"
                    for path in draft["attachments"]:
                        self.telegram.document(path)
                msg = self.telegram.buttons(text, ident, ACTIONS[q["kind"]])
            self.telegram_state["prompts"][ident] = msg["message_id"]
            self.save()

    def receive(self, pending):
        prompts = self.telegram_state["prompts"]
        staged = self.telegram_state["staged"]
        updates = self.telegram.call(
            "getUpdates",
            {
                "offset": self.telegram_state["offset"],
                "timeout": 0,
                "allowed_updates": ["message", "callback_query"],
            },
        )
        for update in updates:
            if callback := update.get("callback_query"):
                msg = callback.get("message", {})
                actor = callback.get("from", {}).get("id")
                ident, _, choice = callback.get("data", "").partition(":")
                if (
                    msg.get("chat", {}).get("id") == actor == self.telegram.chat
                    and ident in pending
                ):
                    kind = pending[ident]["question"]["kind"]
                    valid = dict(
                        RESPONSE_ACTIONS if kind == "question" else ACTIONS[kind]
                    )
                    expected = (
                        staged.get(ident, {}).get("message")
                        if kind == "question"
                        else prompts.get(ident)
                    )
                    if choice in valid and expected == msg["message_id"]:
                        result = self.runner.run(
                            pending[ident],
                            {
                                "id": ident,
                                "choice": choice,
                                "text": staged.get(ident, {}).get("text", ""),
                            },
                        )
                        if (result.get("question") or {}).get("id") != ident:
                            pending.pop(ident)
                            staged.pop(ident, None)
                            prompts.pop(ident, None)
                    self.telegram.call(
                        "answerCallbackQuery", {"callback_query_id": callback["id"]}
                    )
            elif msg := update.get("message"):
                reply_to = msg.get("reply_to_message", {}).get("message_id")
                if (
                    msg.get("chat", {}).get("id")
                    == msg.get("from", {}).get("id")
                    == self.telegram.chat
                ):
                    for ident, prompt in prompts.items():
                        if (
                            prompt == reply_to
                            and ident in pending
                            and pending[ident]["question"]["kind"] == "question"
                            and msg.get("text")
                        ):
                            approval = self.telegram.buttons(
                                msg["text"], ident, RESPONSE_ACTIONS
                            )
                            staged[ident] = {
                                "text": msg["text"],
                                "message": approval["message_id"],
                            }
                            break
            self.telegram_state["offset"] = update["update_id"] + 1
            self.save()

    def tick(self):
        pending = self.pending()
        self.notify(pending)
        self.receive(pending)
        held = any(
            d["question"]["kind"] == "challenge" for d in self.pending().values()
        )
        if held and not self.runner.workflow.browser.background_safe:
            return
        if time.monotonic() >= self.recheck_at:
            self.recheck_at = time.monotonic() + 120
            for snap in self.runner.snapshots():
                state = snap.values
                if (state.get("question") or {}).get(
                    "kind"
                ) == "uncertain" or state.get("status") == "submission_uncertain":
                    try:
                        self.runner.reconcile(state)
                    except Exception as exc:  # noqa: BLE001
                        print(
                            state["dossier"],
                            type(exc).__name__,
                            file=sys.stderr,
                            flush=True,
                        )
        for item in self.queue.items():
            try:
                state = self.runner.run(item)
            except Exception as exc:  # noqa: BLE001
                # Les erreurs de fournisseur peuvent porter des données privées.
                print(item["dossier"], type(exc).__name__, file=sys.stderr, flush=True)
                continue
            if state.get("question"):
                self.notify(self.pending())
                if (
                    state["question"]["kind"] == "challenge"
                    and not self.runner.workflow.browser.background_safe
                ):
                    break


def settings(data):
    return {**dotenv_values(data / ".env"), **os.environ}


def services(queue, env):
    required = (
        "APPLICATIONS_BROWSER_COMMAND",
        "APPLICATIONS_LETTER_TEMPLATE",
        "APPLICATIONS_TELEGRAM_TOKEN",
        "APPLICATIONS_TELEGRAM_CHAT",
    )
    if any(not env.get(name) for name in required):
        raise ValueError("applications_configuration_incomplete")
    policy_path = env.get("APPLICATIONS_BROWSER_POLICY")
    policy = (
        json.loads(Path(policy_path).read_text())
        if policy_path and Path(policy_path).is_file()
        else {}
    )
    command = json.loads(env["APPLICATIONS_BROWSER_COMMAND"])
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(arg, str) for arg in command)
    ):
        raise ValueError("applications_browser_command_invalid")
    if any("--headless" in arg for arg in command):
        raise ValueError("applications_browser_must_be_visible")
    if not shutil.which(command[0]):
        raise ValueError("applications_browser_command_missing")
    if not Path(env["APPLICATIONS_LETTER_TEMPLATE"]).is_file():
        raise ValueError("applications_letter_template_missing")
    documents = queue if hasattr(queue, "dossier_document") else None
    browser = Browsentic(
        queue.data, command, policy, policy_path=policy_path, documents=documents
    )
    if env.get("APPLICATIONS_ACCOUNT_KEY_FILE") and documents:
        from .accounts import PortalAccounts

        browser.accounts = PortalAccounts(
            queue, env["APPLICATIONS_ACCOUNT_KEY_FILE"], policy.get("account_pages", [])
        )
    return Runner(
        queue,
        browser,
        Writer(
            queue.data,
            env["APPLICATIONS_LETTER_TEMPLATE"],
            env.get("APPLICATIONS_HUMANIZER"),
            documents=documents,
        ),
        Mail(env),
        trace_port=env.get("APPLICATIONS_TRACE_LOCAL_PORT"),
    ), Telegram(env["APPLICATIONS_TELEGRAM_TOKEN"], env["APPLICATIONS_TELEGRAM_CHAT"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--once", action="store_true")
    address = commands.add_parser("confirm-address")
    address.add_argument("--mode", choices=("recipe", "production"), required=True)
    metrics = commands.add_parser("metrics")
    metrics.add_argument("--discovery", type=Path)
    for name in ("launch", "status"):
        command = commands.add_parser(name)
        command.add_argument("--discovery", type=Path)
        command.add_argument("--cycle", required=True, type=lambda s: UUID(s).hex)
        if name == "launch":
            command.add_argument(
                "--mode", choices=("recipe", "production"), required=True
            )
            command.add_argument(
                "--queue-only",
                action="store_true",
                help="Ouvrir le lot sans démarrer le worker",
            )
            command.add_argument("--offer", action="append", default=[])
    args = parser.parse_args()
    try:
        return dispatch(args)
    except (OSError, ValueError, KeyError) as exc:
        print(
            type(exc).__name__ + " · configuration ou état du graphe indisponible",
            file=sys.stderr,
        )
        return 1


def dispatch(args):
    data = args.state.resolve()
    env = settings(data)
    dsn = env.get("APPLICATIONS_POSTGRES_DSN")
    if dsn:
        from .postgres_queue import PostgresQueue

        queue = PostgresQueue(data, dsn, env.get("APPLICATIONS_CANDIDATE"))
        if args.command == "confirm-address":
            from getpass import getpass

            from .accounts import confirm_address

            address = getpass("Adresse principale à confirmer : ").strip()
            if address != getpass("Confirmer l’adresse principale : ").strip():
                raise ValueError("applications_address_mismatch")
            confirm_address(queue, args.mode, address)
            return 0
        if args.command == "status":
            return postgres_status(queue, args.cycle)
        if args.command == "metrics":
            print(json.dumps(postgres_metrics(queue)))
            return 0
    else:
        if args.command != "serve" and not getattr(args, "discovery", None):
            raise ValueError("applications_discovery_required")
        if args.command == "metrics":
            print(json.dumps(application_metrics(data, args.discovery.resolve())))
            return 0
        if args.command == "status":
            return status(data, args)
        queue = Queue(data)
    discovery = args.discovery.resolve() if getattr(args, "discovery", None) else None
    if args.command == "launch" and args.queue_only:
        print(
            json.dumps(
                {"lot": queue.launch(discovery, args.cycle, args.mode, args.offer)}
            )
        )
        return 0
    runner, telegram = services(queue, env)
    if args.command == "launch":
        runner.close()
        if args.mode == "recipe" and not runner.workflow.browser.actions:
            raise ValueError("applications_recipe_actions_missing")
        if args.mode == "production" and any(
            not env.get(key)
            for key in (
                "APPLICATIONS_SMTP_HOST",
                "APPLICATIONS_SMTP_USER",
                "APPLICATIONS_SMTP_PASSWORD",
                "APPLICATIONS_HUMANIZER",
            )
        ):
            raise ValueError("applications_mail_configuration_incomplete")
        lot = queue.launch(discovery, args.cycle, args.mode, args.offer)
        fd = os.open(
            queue.data / "worker.log", os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600
        )
        with os.fdopen(fd, "a") as log:
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    __package__ + ".worker",
                    "--state",
                    str(queue.data),
                    "serve",
                ],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        print(json.dumps({"lot": lot}))
        return 0
    with (queue.data / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            runner.close()
            return 0
        try:
            worker = Worker(queue, runner, telegram)
            while True:
                try:
                    worker.tick()
                except Exception as exc:  # noqa: BLE001
                    print(type(exc).__name__, file=sys.stderr, flush=True)
                    if args.once:
                        return 1
                if args.once:
                    return 0
                time.sleep(4)
        finally:
            runner.close()


def postgres_status(queue, cycle):
    with queue.connect() as db:
        rows = queue.selection(db, cycle)
        ids = {
            r["identity"]: str(r["id"])
            for r in db.execute(
                """SELECT identity,id FROM applications.dossiers WHERE candidate=%s
               ORDER BY (mode='production')""",
                (queue.candidate,),
            )
        }
    counts = {
        "prioritaires": sum(not row["incertitude"] for row in rows),
        "incertaines": sum(bool(row["incertitude"]) for row in rows),
        "dossiers": {},
    }
    runner = Runner(queue, None, None, None)
    try:
        for row in rows:
            dossier = ids.get(row["identity"])
            state = runner.graph.get_state(config(dossier)).values if dossier else {}
            counts["dossiers"][row["content"]["key"]] = state.get("status", "queued")
        counts["confirmed_today"] = runner.count(runner.workflow.now().date())
    finally:
        runner.close()
    print(json.dumps(counts))
    return 0


def postgres_metrics(queue):
    with queue.connect() as db:
        rows = db.execute(
            """SELECT DISTINCT s.identity,d.id FROM api.offres_retenues_v1 s
                            LEFT JOIN applications.dossiers d ON d.identity=s.identity
                            AND d.candidate=%s AND d.mode='production'""",
            (queue.candidate,),
        ).fetchall()
    return count_snapshots(queue, {str(r["id"]) for r in rows if r["id"]}, len(rows))


def application_metrics(data, discovery):
    counts = {"pipe": 0, "active": 0, "submitted": 0, "errors": 0}
    source = discovery / "discovery.sqlite3"
    if not source.exists():
        return counts
    with database(source.as_uri() + "?mode=ro") as db:
        dossiers = {
            sha256(row["identity"].encode()).hexdigest()
            for row in retained_rows(db, "")
        }
    counts["pipe"] = len(dossiers)
    if not dossiers or not (data / "queue.sqlite3").exists():
        return counts
    return count_snapshots(Queue(data), dossiers, len(dossiers))


def count_snapshots(queue, dossiers, total):
    counts = {"pipe": total, "active": 0, "submitted": 0, "errors": 0}
    runner = Runner(queue, None, None, None)
    try:
        for snap in runner.snapshots():
            state = snap.values
            if (
                state.get("dossier") not in dossiers
                or state.get("mode") != "production"
            ):
                continue
            if state.get("evidence"):
                counts["submitted"] += 1
                counts["pipe"] -= 1
            elif (
                state.get("status")
                in {"blocked", "version_conflict", "submission_uncertain"}
                or (state.get("question") or {}).get("kind") == "uncertain"
                or any(task.error for task in snap.tasks)
            ):
                counts["errors"] += 1
            elif state.get("status") != "deferred":
                counts["active"] += 1
    finally:
        runner.close()
    return counts


def status(data, args):
    items = selected(args.discovery.resolve(), args.cycle)
    counts = {
        "prioritaires": sum(not item["uncertain"] for item in items),
        "incertaines": sum(item["uncertain"] for item in items),
    }
    path = data / "queue.sqlite3"
    if path.exists():
        queue = Queue(data)
        runner = Runner(queue, None, None, None)
        try:
            counts["dossiers"] = {}
            for item in items:
                state = runner.graph.get_state(config(item["dossier"])).values
                status = state.get("status", "queued")
                if (
                    state
                    and not state.get("submission")
                    and runner.destination_changed(state)
                ):
                    status = "version_conflict"
                counts["dossiers"][item["offer"]["key"]] = status
            counts["confirmed_today"] = runner.count(runner.workflow.now().date())
        finally:
            runner.close()
    print(json.dumps(counts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
