"""Transitions du dossier. Le checkpoint précède tout appel de transmission."""

import json
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import TypedDict
from uuid import uuid4
from zoneinfo import ZoneInfo

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

ZONE = ZoneInfo("Africa/Casablanca")


class State(TypedDict, total=False):
    dossier: str
    mode: str
    offer: dict
    cv: str
    cv_text: str
    version: str
    status: str
    next_node: str
    question: dict | None
    answers: list[dict]
    letter: str
    submission: dict | None
    mail: dict | None
    draft: dict | None
    mail_status: str
    evidence: dict | None
    planned_action: dict | None
    browser_tab: int
    mail_approval: str
    due: str
    reason: str


def fingerprint(path):
    return sha256(Path(path).read_bytes()).hexdigest()


class Workflow:
    def __init__(self, browser, writer, mail, memory, count, now=None):
        self.browser = browser
        self.writer = writer
        self.mail = mail
        self.memory = memory
        self.count = count
        self.now = now or (lambda: datetime.now(ZONE))
        self.permits = set()

    def wait_for(self, kind, **details):
        return {
            "status": "waiting",
            "question": {"id": uuid4().hex, "kind": kind, **details},
            "next_node": "wait",
        }

    def fill(self, state):
        if state["mode"] == "production" and getattr(
            self.browser, "native_submission", False
        ):
            return {"status": "ready", "next_node": "prepare_submission"}
        return self.form_result(
            state, self.browser.fill(state, self.memory.read(state))
        )

    def form_result(self, state, result):
        kind = result["kind"]
        tab = {"browser_tab": result["browser_tab"]} if "browser_tab" in result else {}
        if kind == "ready":
            action = result.get("action")
            if state["mode"] == "recipe":
                return {
                    **tab,
                    "status": "recipe_ready",
                    "planned_action": action,
                    "next_node": "draft",
                }
            return {
                **tab,
                "status": "ready",
                "planned_action": action,
                "next_node": "prepare_submission",
            }
        if kind == "letter" and not state.get("letter"):
            return {**tab, "next_node": "letter"}
        if kind in {"question", "challenge", "registration"}:
            return {
                **tab,
                **self.wait_for(
                    kind, text=result["text"], scope=result.get("scope", {})
                ),
            }
        return {
            **tab,
            "status": "blocked",
            "reason": result.get("text", "Formulaire bloqué."),
            "next_node": END,
        }

    def letter(self, state):
        return {"letter": self.writer.letter(state), "next_node": "fill"}

    def wait(self, state):
        question = state["question"]
        answer = interrupt(question)
        kind = question["kind"]
        if kind == "mail":
            if (
                answer["choice"] == "approve"
                and self.draft_version(state["draft"]) == question["version"]
            ):
                return {
                    "question": None,
                    "status": "submitted",
                    "next_node": "prepare_mail",
                    "mail_approval": question["version"],
                }
            if answer["choice"] == "approve":
                return {"question": None, "next_node": "draft"}
            return {
                "question": None,
                "status": "submitted",
                "mail_status": "revision",
                "next_node": END,
            }
        if kind == "recipe_mail":
            return {
                "question": None,
                "status": "recipe_ready",
                "mail_status": "recipe_ready",
                "next_node": END,
            }
        if kind == "uncertain":
            receipt = answer.get("receipt") or self.browser.verify(state)
            if receipt:
                return {"question": None, **self.record_submission(state, receipt)}
            if answer["choice"] == "retry":
                return {
                    "question": None,
                    "submission": None,
                    "status": "ready",
                    "next_node": "fill",
                }
            return {
                "question": None,
                "status": "submission_uncertain",
                "next_node": END,
            }
        if kind == "registration" and answer["choice"] == "deny":
            self.memory.save(state, question, answer)
            return {
                "question": None,
                "status": "blocked",
                "reason": "Inscription refusée.",
                "next_node": END,
            }
        if answer["choice"] == "remember" or kind == "registration":
            self.memory.save(state, question, answer)
        answers = list(state.get("answers", []))
        answers.append({"question": question, **answer})
        return {
            "question": None,
            "answers": answers,
            "status": "preparing",
            "next_node": "fill",
        }

    def prepare_submission(self, state):
        today = self.now().astimezone(ZONE).date()
        if self.count(today) >= 40:
            return {
                "status": "deferred",
                "due": (today + timedelta(days=1)).isoformat(),
                "next_node": END,
            }
        opened = self.open_attempt("submission")
        if getattr(self.browser, "native_submission", False):
            opened["submission"]["native"] = True
        return opened

    def open_attempt(self, operation):
        attempt = uuid4().hex
        self.permits.add(attempt)
        return {operation: {"id": attempt, "status": "open"}, "next_node": operation}

    def submission(self, state):
        attempt = state["submission"]
        if attempt["id"] not in self.permits:
            return self.verify(state)
        self.permits.remove(attempt["id"])
        if state["mode"] != "production":
            raise ValueError("submission_mode_invalid")
        if attempt.get("native"):
            result = self.browser.run_form(state, self.memory.read(state))
            tab = (
                {"browser_tab": result["browser_tab"]}
                if "browser_tab" in result
                else {}
            )
            if receipt := result.get("receipt"):
                return {**tab, **self.record_submission(state, receipt)}
            if result["transmission_attempted"] or result["kind"] in {
                "unknown",
                "submitted",
            }:
                return {**tab, **self.verify({**state, **tab})}
            return {"submission": None, **self.form_result(state, result)}
        receipt = self.browser.submit(state, attempt["id"])
        return self.record_submission(state, receipt) if receipt else self.verify(state)

    def verify(self, state):
        receipt = self.browser.verify(state)
        if receipt:
            return self.record_submission(state, receipt)
        return self.wait_for("uncertain", text="Dépôt à vérifier sur le portail.")

    def record_submission(self, state, receipt):
        observed = self.now()
        try:
            sent = datetime.fromisoformat(receipt.get("sent_at") or "")
            if sent.utcoffset() is None:
                raise ValueError
        except ValueError:
            sent, source = observed, "observation"
        else:
            source = "portail"
        return {
            "status": "submitted",
            "submission": {**state["submission"], "status": "confirmed"},
            "evidence": {
                **receipt,
                "day": sent.astimezone(ZONE).date().isoformat(),
                "date_source": source,
            },
            "next_node": "draft",
        }

    @staticmethod
    def draft_version(draft):
        data = {
            **draft,
            "attachments": [fingerprint(path) for path in draft["attachments"]],
        }
        return sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def draft(self, state):
        draft = self.writer.draft(state)
        if not draft:
            return {"mail_status": "unavailable", "next_node": END}
        if state["mode"] == "recipe":
            return {
                "draft": draft,
                **self.wait_for(
                    "recipe_mail",
                    text=draft["subject"],
                    version=self.draft_version(draft),
                ),
                "status": "recipe_ready",
                "mail_status": "recipe_ready",
            }
        return {
            "draft": draft,
            "mail_status": "waiting",
            **self.wait_for(
                "mail", text=draft["subject"], version=self.draft_version(draft)
            ),
            "status": "submitted",
        }

    def prepare_mail(self, state):
        if state["mode"] != "production" or not state.get("evidence"):
            raise ValueError("mail_mode_invalid")
        if self.draft_version(state["draft"]) != state["mail_approval"]:
            return {"next_node": "draft"}
        update = self.open_attempt("mail")
        update["mail"]["version"] = state["mail_approval"]
        return {**update, "next_node": "send_mail"}

    def send_mail(self, state):
        attempt = state["mail"]
        ident = attempt["id"]
        if state["mode"] != "production" or not state.get("evidence"):
            raise ValueError("mail_mode_invalid")
        if ident in self.permits:
            self.permits.remove(ident)
            if self.draft_version(state["draft"]) != attempt["version"]:
                return self.draft(state)
            result = self.mail.send(state["draft"], ident)
        else:
            result = self.mail.verify(state["draft"], ident)
        return {
            "mail": {
                **attempt,
                "status": "confirmed" if result else "uncertain",
                "receipt": result,
            },
            "mail_status": "sent" if result else "uncertain",
            "next_node": END,
        }


def build(workflow, checkpointer):
    graph = StateGraph(State)
    nodes = (
        "fill",
        "letter",
        "wait",
        "prepare_submission",
        "submission",
        "draft",
        "prepare_mail",
        "send_mail",
    )
    for node in nodes:
        graph.add_node(node, getattr(workflow, node))
    destinations = [*nodes, END]

    def route(state):
        return state.get("next_node", "fill")

    for node in (*nodes, START):
        graph.add_conditional_edges(node, route, destinations)
    return graph.compile(checkpointer=checkpointer, name="graphe2.applications")
