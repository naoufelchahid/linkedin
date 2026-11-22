"""Transitions du dossier. Le checkpoint précède tout appel de transmission."""

from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import TypedDict
from uuid import uuid4
from zoneinfo import ZoneInfo

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .followup import frozen_draft, manifest, version
from .obstacles import describe
from .telemetry import AttemptTrace

ZONE = ZoneInfo("Africa/Casablanca")


class State(TypedDict, total=False):
    dossier: str
    mode: str
    offer: dict
    cv_hash: str
    cv: str
    cv_text: str
    version: str
    status: str
    next_node: str
    question: dict | None
    answers: list[dict]
    letter_hash: str
    letter: str
    submission: dict | None
    mail: dict | None
    draft: dict | None
    mail_status: str
    evidence: dict | None
    planned_action: dict | None
    browser_tab: int
    mail_review: str
    mail_approval: str
    due: str
    reason: str


def fingerprint(path):
    return sha256(Path(path).read_bytes()).hexdigest()


class Workflow:
    def __init__(
        self, browser, writer, mail, memory, count, now=None, *, trace_port=None
    ):
        self.browser = browser
        self.writer = writer
        self.mail = mail
        self.memory = memory
        self.count = count
        self.now = now or (lambda: datetime.now(ZONE))
        self._permits = set()
        self.followup = None
        self.submissions = None
        self.trace = AttemptTrace(trace_port)

    def wait_for(self, kind, **details):
        return {
            "status": "waiting",
            "question": {"id": uuid4().hex, "kind": kind, **details},
            "next_node": "wait",
        }

    def saved_submission(self, state):
        if self.submissions and (receipt := self.submissions.receipt(state["dossier"])):
            return {
                "status": "submitted",
                "submission": {
                    "id": receipt["id"],
                    "status": "confirmed",
                    "started_at": receipt["started_at"].isoformat(),
                },
                "evidence": receipt["evidence"],
                "next_node": "draft",
            }
        return None

    def fill(self, state):
        if self.submissions and state["mode"] == "production":
            if saved := self.saved_submission(state):
                with self.trace.step(
                    state["dossier"], saved["submission"], "reprise_recu_sql"
                ):
                    return saved
            if active := self.submissions.active(state["dossier"]):
                return {
                    "submission": {
                        **active,
                        "native": getattr(self.browser, "native_submission", False),
                    },
                    "next_node": "submission",
                }
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
        if kind == "account_confirmation":
            confirmations = getattr(self.browser, "confirmations", None)
            if confirmations and confirmations.begin(
                state["dossier"], tab.get("browser_tab")
            ):
                return {
                    **tab,
                    "status": "waiting_account_confirmation",
                    "next_node": END,
                }
            return {
                **tab,
                "status": "blocked",
                "reason": "account_confirmation_unavailable",
                "next_node": END,
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
        path = self.writer.letter(state)
        return {"letter": path, "letter_hash": fingerprint(path), "next_node": "fill"}

    def wait(self, state):
        question = state["question"]
        answer = dict(interrupt(question))
        conflict = answer.pop("version_conflict", False)
        kind = question["kind"]
        if diagnostic := question.get("diagnostic"):
            cleared = self.browser.obstacle_cleared(state, diagnostic)
            if self.submissions:
                self.submissions.obstacle_checked(question["attempt_id"], cleared)
            if not cleared:
                return self.wait_for(
                    kind,
                    text=question["text"],
                    diagnostic=diagnostic,
                    attempt_id=question["attempt_id"],
                )
            return {"question": None, "status": "preparing", "next_node": "fill"}
        if kind in {"mail", "recipe_mail"} and answer["choice"] == "refresh":
            return {"question": None, "next_node": "draft"}
        if kind == "mail":
            if (
                answer["choice"] == "approve"
                and self.draft_version(self.local_draft(state)) == question["version"]
                and (
                    not self.followup
                    or self.followup.approve(
                        state["dossier"], question["id"], question["version"]
                    )
                )
            ):
                return {
                    "question": None,
                    "status": "submitted",
                    "next_node": "prepare_mail",
                    "mail_approval": question["version"],
                    "mail_review": question["id"],
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
                return {
                    "question": None,
                    **self.record_submission(state, receipt, reconciled=True),
                }
            if (
                answer["choice"] == "retry"
                and not self.submissions
                and not state["submission"].get("verify_only")
            ):
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
            "status": "version_conflict" if conflict else "preparing",
            "next_node": END if conflict else "fill",
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
        if self.submissions:
            opened["submission"]["sql_guarded"] = True
        if getattr(self.browser, "native_submission", False):
            opened["submission"]["native"] = True
        return opened

    def open_attempt(self, operation):
        attempt = uuid4().hex
        self._permits.add(attempt)
        return {operation: {"id": attempt, "status": "open"}, "next_node": operation}

    def consume_permit(self, ident):
        if ident not in self._permits:
            return False
        self._permits.remove(ident)
        return True

    def clear_permits(self):
        self._permits.clear()

    def submission(self, state):
        attempt = state["submission"]
        permitted = self.consume_permit(attempt["id"])
        if state["mode"] != "production":
            raise ValueError("submission_mode_invalid")
        if not self.submissions:
            return self.transmit(state) if permitted else self.verify(state)
        fresh, row = self.submissions.begin(state)
        attempt = {
            **attempt,
            "id": row["id"],
            "generation": row["generation"],
            "started_at": row["started_at"].isoformat(),
        }
        state = {**state, "submission": attempt}
        if row["status"] == "no_submission":
            return row["outcome"]
        if not fresh or not (permitted or attempt.get("sql_guarded")):
            with self.trace.step(state["dossier"], attempt, "reprise"):
                return {"submission": attempt, **self.verify(state)}
        with (
            self.submissions.lease(state["dossier"], attempt),
            self.trace.step(state["dossier"], attempt, "transmission"),
        ):
            result = self.transmit({**state, "_mandate_text": row["mandate_text"]})
        return {"submission": attempt, **result}

    def transmit(self, state):
        attempt = state["submission"]
        if attempt.get("native"):
            result = self.browser.run_form(state, self.memory.read(state))
            tab = (
                {"browser_tab": result["browser_tab"]}
                if "browser_tab" in result
                else {}
            )
            diagnostic = describe(result, state)
            if diagnostic:
                if self.submissions:
                    self.submissions.obstacle(attempt["id"], diagnostic)
                if diagnostic["transmission_attempted"]:
                    guard = {**attempt, "verify_only": True}
                    return {
                        **tab,
                        "submission": guard,
                        **self.verify({**state, **tab, "submission": guard}),
                    }
                update = {
                    "submission": None,
                    **tab,
                    **self.wait_for(
                        "challenge"
                        if diagnostic["signal"] == "verification_humaine"
                        else "obstacle",
                        text=diagnostic["observation"],
                        diagnostic=diagnostic,
                        attempt_id=attempt["id"],
                    ),
                }
                if self.submissions and not self.submissions.finish(
                    state, outcome=update
                ):
                    return self.verify(state)
                return update
            if receipt := result.get("receipt"):
                return {**tab, **self.record_submission(state, receipt)}
            if result["transmission_attempted"] or result["kind"] in {
                "unknown",
                "submitted",
            }:
                return {**tab, **self.verify({**state, **tab})}
            update = {"submission": None, **self.form_result(state, result)}
            if self.submissions and not self.submissions.finish(state, outcome=update):
                return self.verify(state)
            return update
        receipt = self.browser.submit(state, attempt["id"])
        return self.record_submission(state, receipt) if receipt else self.verify(state)

    def verify(self, state):
        if saved := self.saved_submission(state):
            return saved
        receipt = self.browser.verify(state)
        if receipt:
            return self.record_submission(state, receipt, reconciled=True)
        return self.wait_for("uncertain", text="Dépôt à vérifier sur le portail.")

    def record_submission(self, state, receipt, reconciled=False):
        if saved := self.saved_submission(state):
            return saved
        if self.submissions and "generation" not in state["submission"]:
            # Les checkpoints précédant la migration peuvent déjà être en vérification.
            _, row = self.submissions.begin(state)
            state = {
                **state,
                "submission": {
                    **state["submission"],
                    "id": row["id"],
                    "generation": row["generation"],
                    "started_at": row["started_at"].isoformat(),
                },
            }
        observed = self.now()
        try:
            sent = datetime.fromisoformat(receipt.get("sent_at") or "")
            if sent.utcoffset() is None:
                raise ValueError
        except ValueError:
            sent, source = observed, "observation"
        else:
            source = "portail"
        update = {
            "status": "submitted",
            "submission": {**state["submission"], "status": "confirmed"},
            "evidence": {
                **receipt,
                "day": sent.astimezone(ZONE).date().isoformat(),
                "date_source": source,
            },
            "next_node": "draft",
        }

        if self.submissions:
            with self.trace.step(state["dossier"], state["submission"], "recu_sql"):
                if not self.submissions.finish(
                    state, evidence=update["evidence"], reconciled=reconciled
                ):
                    return self.saved_submission(state) or self.wait_for(
                        "uncertain", text="Dépôt à vérifier sur le portail."
                    )
        return update

    def local_draft(self, state):
        draft = state["draft"]
        return (
            self.followup.local_draft(state["dossier"], draft)
            if self.followup
            else draft
        )

    @staticmethod
    def draft_version(draft):
        return version(manifest(draft))

    def draft(self, state):
        if self.followup and (existing := self.followup.attempt(state["dossier"])):
            return {
                "mail": {
                    "id": existing["attempt_id"].hex,
                    "version": existing["version"],
                },
                "next_node": "send_mail",
            }
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
        data = manifest(draft)
        review = self.wait_for("mail", text=draft["subject"], version=version(data))
        if self.followup:
            self.followup.present(state["dossier"], review["question"]["id"], data)
        return {
            "draft": draft,
            "mail_status": "waiting",
            **review,
            "status": "submitted",
        }

    def prepare_mail(self, state):
        if state["mode"] != "production" or not state.get("evidence"):
            raise ValueError("mail_mode_invalid")
        if self.draft_version(self.local_draft(state)) != state["mail_approval"]:
            return {"next_node": "draft"}
        update = self.open_attempt("mail")
        update["mail"]["version"] = state["mail_approval"]
        return {**update, "next_node": "send_mail"}

    def send_mail(self, state):
        attempt = state["mail"]
        ident = attempt["id"]
        if state["mode"] != "production" or not state.get("evidence"):
            raise ValueError("mail_mode_invalid")
        existing = self.followup.attempt(state["dossier"]) if self.followup else None
        allowed = self.consume_permit(ident)
        if self.followup and state.get("mail_review"):
            allowed = existing is None
        if existing:
            ident = existing["attempt_id"].hex
            attempt = {"id": ident, "version": existing["version"]}
            allowed = False
        if allowed:
            with frozen_draft(self.local_draft(state)) as exact:
                if self.draft_version(exact) != attempt["version"]:
                    return self.draft(state)
                if self.followup and not self.followup.claim(
                    state["dossier"],
                    state.get("mail_review"),
                    attempt["version"],
                    ident,
                ):
                    return self.draft(state)
                result = self.mail.send(exact, ident)
        else:
            result = (existing or {}).get("receipt") or self.mail.verify(
                state.get("draft"), ident
            )
        if self.followup and result:
            self.followup.confirm(ident, result)
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
