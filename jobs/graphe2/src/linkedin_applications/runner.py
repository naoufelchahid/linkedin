"""Pilotage du checkpoint et reprise depuis la file locale."""

import sqlite3
from contextlib import ExitStack, closing, nullcontext
from datetime import date
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from langsmith import tracing_context

from .graph import ZONE, Workflow, build, fingerprint
from .storage import Memory


def config(dossier):
    return {"configurable": {"thread_id": dossier}, "recursion_limit": 50}


class Runner:
    def __init__(self, queue, browser, writer, mail, now=None, *, trace_port=None):
        self.resources = ExitStack()
        if hasattr(queue, "checkpointer"):
            saver = self.resources.enter_context(queue.checkpointer())
        else:
            path = queue.data / "checkpoints.sqlite3"
            path.touch(mode=0o600, exist_ok=True)
            db = self.resources.enter_context(
                closing(sqlite3.connect(path, check_same_thread=False))
            )
            saver = SqliteSaver(db)
        self.queue = queue
        self.workflow = Workflow(
            browser,
            writer,
            mail,
            Memory(queue.data, getattr(queue, "candidate_answers", None)),
            self.count,
            now,
            trace_port=trace_port,
        )
        self.workflow.submissions = getattr(queue, "submissions", None)
        self.workflow.followup = getattr(queue, "followup", None)
        self.graph = build(self.workflow, saver)

    def close(self):
        self.workflow.trace.close()
        self.resources.close()

    def snapshots(self):
        for dossier in dict.fromkeys(item["dossier"] for item in self.queue.items()):
            yield self.graph.get_state(config(dossier))

    def count(self, day: date):
        return sum(
            (snap.values.get("evidence") or {}).get("day") == day.isoformat()
            for snap in self.snapshots()
        )

    def checkpoint_lock(self, dossier):
        return (
            self.queue.checkpoint_lock(dossier)
            if hasattr(self.queue, "checkpoint_lock")
            else nullcontext(True)
        )

    def busy(self, item):
        return {
            **self.graph.get_state(config(item["dossier"])).values,
            "dossier": item["dossier"],
            "status": "in_progress",
        }

    def run(self, item, reply=None):
        with (
            tracing_context(enabled=False),
            self.checkpoint_lock(item["dossier"]) as acquired,
        ):
            if not acquired:
                return self.busy(item)
            try:
                return self._run(item, reply)
            finally:
                self.workflow.clear_permits()

    def _run(self, item, reply):
        cfg = config(item["dossier"])
        snap = self.graph.get_state(cfg)
        current = snap.values
        question = current.get("question") or {}
        ledger = getattr(self.queue, "candidate_answers", None)
        if (
            ledger
            and reply
            and question.get("kind") == "question"
            and reply.get("id") == question["id"]
        ):
            reply = ledger.reply(question["id"])
        if not current:
            cv = Path(item["cv"])
            if fingerprint(cv) != item["cv_hash"]:
                raise ValueError("cv_snapshot_integrity")
            return self.graph.invoke(item, cfg, durability="sync")
        if not current.get("submission") and self.destination_changed(current):
            question = current.get("question") or {}
            if (
                snap.interrupts
                and question.get("kind") == "question"
                and reply
                and reply["id"] == question["id"]
            ):
                return self.graph.invoke(
                    Command(resume={**reply, "version_conflict": True}),
                    cfg,
                    durability="sync",
                )
            return {**current, "status": "version_conflict"}
        if current["mode"] != item["mode"]:
            if (
                current["mode"] == "recipe"
                and item["mode"] == "production"
                and not snap.next
            ):
                return self.graph.invoke(
                    {
                        "mode": "production",
                        "status": "preparing",
                        "draft": None,
                        "mail_status": "",
                        "next_node": "fill",
                    },
                    cfg,
                    durability="sync",
                )
            return current
        if snap.interrupts:
            question = current["question"]
            if reply and reply["id"] == question["id"]:
                return self.graph.invoke(Command(resume=reply), cfg, durability="sync")
            return current
        if current.get("status") == "waiting_account_confirmation" and not snap.next:
            confirmations = getattr(self.workflow.browser, "confirmations", None)
            if confirmations and confirmations.poll(current["dossier"]):
                return self.graph.invoke(
                    {"status": "preparing", "next_node": "fill"}, cfg, durability="sync"
                )
            return current
        if current.get("status") == "version_conflict" and not snap.next:
            return self.graph.invoke({"next_node": "fill"}, cfg, durability="sync")
        if snap.next:
            return self.graph.invoke(None, cfg, durability="sync")
        today = self.workflow.now().astimezone(ZONE).date().isoformat()
        if current.get("status") == "deferred" and current["due"] <= today:
            return self.graph.invoke({"next_node": "fill"}, cfg, durability="sync")
        return current

    def destination_changed(self, state):
        return any(
            item["dossier"] == state["dossier"]
            and item["version"] != state["version"]
            and any(
                item["offer"].get(key) != state["offer"].get(key)
                for key in ("destination", "requisition")
            )
            for item in self.queue.items()
        )

    def reconcile_mail(self, state):
        with (
            tracing_context(enabled=False),
            self.checkpoint_lock(state["dossier"]) as acquired,
        ):
            if not acquired:
                return self.busy(state)
            return self.graph.invoke(
                {"next_node": "send_mail"}, config(state["dossier"]), durability="sync"
            )

    def reconcile(self, state):
        with (
            tracing_context(enabled=False),
            self.checkpoint_lock(state["dossier"]) as acquired,
            self.workflow.trace.step(
                state["dossier"], state.get("submission"), "rapprochement"
            ),
        ):
            return self._reconcile(state) if acquired else self.busy(state)

    def _reconcile(self, state):
        stored = self.workflow.saved_submission(state)
        receipt = stored["evidence"] if stored else self.workflow.browser.verify(state)
        if not receipt:
            return state
        if state.get("question"):
            return self._run(
                state,
                {
                    "id": state["question"]["id"],
                    "choice": "confirmed",
                    "receipt": receipt,
                },
            )
        with tracing_context(enabled=False):
            return self.graph.invoke(
                {
                    "question": None,
                    **self.workflow.record_submission(state, receipt, reconciled=True),
                },
                config(state["dossier"]),
                durability="sync",
            )
