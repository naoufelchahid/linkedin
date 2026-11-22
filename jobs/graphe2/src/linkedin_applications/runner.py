"""Pilotage du checkpoint et reprise depuis la file locale."""

import sqlite3
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
    def __init__(self, queue, browser, writer, mail, now=None):
        path = queue.data / "checkpoints.sqlite3"
        path.touch(mode=0o600, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        saver = SqliteSaver(self.connection)
        self.queue = queue
        self.workflow = Workflow(
            browser, writer, mail, Memory(queue.data), self.count, now
        )
        self.workflow.submissions = getattr(queue, "submissions", None)
        self.graph = build(self.workflow, saver)

    def close(self):
        self.connection.close()

    def snapshots(self):
        for dossier in dict.fromkeys(item["dossier"] for item in self.queue.items()):
            yield self.graph.get_state(config(dossier))

    def count(self, day: date):
        return sum(
            (snap.values.get("evidence") or {}).get("day") == day.isoformat()
            for snap in self.snapshots()
        )

    def run(self, item, reply=None):
        with tracing_context(enabled=False):
            try:
                return self._run(item, reply)
            finally:
                self.workflow.clear_permits()

    def _run(self, item, reply):
        cfg = config(item["dossier"])
        snap = self.graph.get_state(cfg)
        current = snap.values
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

    def reconcile(self, state):
        stored = self.workflow.saved_submission(state)
        receipt = stored["evidence"] if stored else self.workflow.browser.verify(state)
        if not receipt:
            return state
        if state.get("question"):
            return self.run(
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
