import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from linkedin_applications.graph import ZONE, fingerprint
from linkedin_applications.runner import Runner, config
from linkedin_applications.storage import Queue, database, selected
from linkedin_discovery.model import normalize
from linkedin_discovery.store import Store


class Crash(RuntimeError):
    pass


class Browser:
    background_safe = True
    ready = {"kind": "ready", "action": {"id": "submit"}}

    def __init__(self):
        self.forms = []
        self.calls = []
        self.receipts = {}
        self.outcome = "confirmed"
        self.visible = True
        self.sent_at = None

    def fill(self, state, memory):
        self.calls.append(("fill", state["dossier"]))
        if self.forms:
            return self.forms.pop(0)
        return self.ready

    def submit(self, state, attempt):
        key = state["dossier"]
        self.calls.append(("submit", key))
        if self.outcome == "before":
            raise Crash
        self.receipts[key] = {"reference": key, "sent_at": self.sent_at}
        if self.outcome == "after":
            raise Crash
        return self.receipts[key] if self.outcome == "confirmed" else None

    def verify(self, state):
        key = state["dossier"]
        self.calls.append(("verify", key))
        return self.receipts.get(key) if self.visible else None


class Writer:
    def __init__(self, path):
        self.attachment = path / "letter.pdf"
        self.attachment.write_bytes(b"%PDF letter")
        self.enabled = False

    def draft(self, state):
        if self.enabled:
            return dict(
                recipient="job@example.org",
                subject="Candidature",
                body="Bonjour",
                attachments=[state["cv"], str(self.attachment)],
            )


class Mail:
    def __init__(self):
        self.sent = {}
        self.crash = False
        self.visible = True

    def send(self, draft, attempt):
        self.sent[attempt] = {"id": attempt}
        if self.crash:
            raise Crash
        return self.sent[attempt]

    def verify(self, draft, attempt):
        return self.sent.get(attempt) if self.visible else None


class Environment:
    def __init__(self, path):
        self.queue = Queue(path)
        self.browser, self.writer, self.mail = Browser(), Writer(path), Mail()
        self.clock = datetime(2026, 11, 23, 14, tzinfo=ZONE)
        self.runner = None
        self.reopen()

    def reopen(self):
        if self.runner:
            self.runner.close()
        self.runner = Runner(
            self.queue, self.browser, self.writer, self.mail, lambda: self.clock
        )

    def item(self, name, mode="production", cycle=None):
        cv = self.queue.data / (name + ".pdf")
        cv.write_bytes(b"%PDF cv")
        item = dict(
            dossier=name,
            version="v1",
            mode=mode,
            offer={"title": name},
            cv=str(cv),
            cv_hash=fingerprint(cv),
            cv_text="CV",
        )
        with database(self.queue.path) as db:
            lot = db.execute(
                "INSERT INTO lots(cycle,mode) VALUES(?,?)", (cycle or uuid4().hex, mode)
            ).lastrowid
            db.execute(
                "INSERT INTO items VALUES(?,?,?,?)", (lot, name, 0, json.dumps(item))
            )
        return item


@pytest.fixture
def env(tmp_path):
    env = Environment(tmp_path)
    yield env
    env.runner.close()


@pytest.mark.parametrize("outcome", ["before", "after"])
def test_panne_autour_du_clic(env, outcome):
    first, other = env.item("a"), env.item("b")
    env.browser.outcome = outcome
    with pytest.raises(Crash):
        env.runner.run(first)
    env.reopen()
    state = env.runner.run(first)
    assert env.browser.calls[-1] == ("verify", "a")
    assert env.browser.calls.count(("submit", "a")) == 1
    assert state["status"] == ("waiting" if outcome == "before" else "submitted")
    assert len(env.browser.receipts) == (outcome == "after")
    env.browser.outcome = "confirmed"
    assert env.runner.run(other)["status"] == "submitted"


def test_deux_annonces_un_depot(env):
    first = env.item("a")
    repeated = env.item("a")
    distinct = env.item("b")
    for item in (first, repeated, distinct):
        assert env.runner.run(item)["status"] == "submitted"
    assert env.browser.calls.count(("submit", "a")) == 1
    assert env.runner.count(env.clock.date()) == 2


@pytest.mark.parametrize("immediate", [True, False])
def test_deux_lots_a_39(env, immediate):
    for index in range(39):
        env.runner.run(env.item(str(index)))
    first, second = env.item("first"), env.item("second")
    if not immediate:
        env.browser.outcome = "unknown"
        env.browser.visible = False
    state = env.runner.run(first)
    env.browser.outcome = "confirmed"
    state2 = env.runner.run(second)
    if immediate:
        assert state2["status"] == "deferred"
        assert env.runner.count(env.clock.date()) == 40
    else:
        assert state2["status"] == "submitted"
        assert state["question"]["kind"] == "uncertain"
        assert env.runner.count(env.clock.date()) == 40
        env.browser.visible = True
        assert env.runner.reconcile(state)["status"] == "submitted"
        assert env.runner.count(env.clock.date()) == 41


@pytest.mark.parametrize("timestamp", ["2026-11-23T23:59:00+01:00", None])
def test_confirmation_a_minuit(env, timestamp):
    first = env.item("a")
    env.browser.outcome = "after"
    env.browser.sent_at = timestamp
    with pytest.raises(Crash):
        env.runner.run(first)
    env.clock = datetime(2026, 11, 24, 0, 3, tzinfo=ZONE)
    env.reopen()
    state = env.runner.run(first)
    assert state["evidence"]["day"] == ("2026-11-23" if timestamp else "2026-11-24")
    assert state["evidence"]["date_source"] == (
        "portail" if timestamp else "observation"
    )
    assert env.runner.run(first)["evidence"] == state["evidence"]


@pytest.mark.parametrize("choice", ["remember", "once"])
def test_dossier_en_attente_nouveau_lot(env, choice):
    first = env.item("a")
    env.browser.forms = [{"kind": "question", "text": "Préavis ?", "scope": "salarié"}]
    state = env.runner.run(first)
    question = state["question"]
    env.reopen()
    second = {**first, "cv_text": "Nouveau CV", "version": "v2"}
    assert env.runner.run(second)["question"] == question
    reply = {"id": question["id"], "choice": choice, "text": "30 jours"}
    saved = env.runner.run(second, reply)
    assert saved["answers"][0]["text"] == "30 jours"
    assert saved["version"] == "v1"
    assert bool(env.runner.workflow.memory.read(saved)) == (choice == "remember")
    assert env.runner.run(second, reply)["answers"] == saved["answers"]


def test_correction_humaine_et_priorite(tmp_path):
    data = tmp_path / "discovery"
    store = Store(data)
    cycle = store.create_cycle(b"%PDF cv", "CV", "prompt", {})
    for index, codex, human, uncertain in (
        (1, "retenir", None, False),
        (2, "retenir", None, True),
        (3, "écarter", "retenir", False),
        (4, "retenir", "écarter", False),
    ):
        raw = {
            "url": f"https://www.linkedin.com/jobs/view/{index}",
            "title": str(index),
        }
        version = store.ingest(cycle, "one", raw, normalize(raw))
        item = store.qualification(store.cycle(cycle), version)
        store.execute(
            "UPDATE qualifications SET result=?,status='done' WHERE id=?",
            (json.dumps({"verdict": codex, "incertitude": uncertain}), item["id"]),
        )
        if human:
            store.execute(
                "INSERT INTO reports VALUES(?,?,?,?,?,?)",
                (str(index), cycle, "now", "{}", "report", "hash"),
            )
            store.execute(
                "INSERT INTO review_items VALUES(?,?,?,?)",
                (str(index), 1, version, item["id"]),
            )
            store.review(str(index), 1, human)
    store.close()
    items = selected(data, cycle)
    assert {item["offer"]["title"] for item in items[:2]} == {"1", "3"}
    assert items[2]["offer"]["title"] == "2"
    queue = Queue(tmp_path / "applications")
    keys = [items[0]["offer"]["key"], items[2]["offer"]["key"]]
    lot = queue.launch(data, cycle, "recipe", keys)
    assert queue.launch(data, cycle, "recipe", keys) == lot
    assert [item["offer"]["key"] for item in queue.items()] == keys
    with pytest.raises(ValueError, match="recipe_offers_invalid"):
        queue.launch(data, cycle, "recipe", ["inconnue"])
    with pytest.raises(ValueError, match="recipe_offers_invalid"):
        queue.launch(data, cycle, "production", keys)


@pytest.mark.parametrize("visible", [True, False])
def test_mail_accepte_reponse_perdue(env, visible):
    item = env.item("a")
    env.writer.enabled = True
    env.mail.crash = True
    state = env.runner.run(item)
    with pytest.raises(Crash):
        env.runner.run(item, {"id": state["question"]["id"], "choice": "approve"})
    env.mail.visible = visible
    env.reopen()
    state = env.runner.run(item)
    assert state["status"] == "submitted"
    assert state["mail_status"] == ("sent" if visible else "uncertain")
    assert len(env.mail.sent) == 1


def test_brouillon_modifie_requiert_un_nouvel_accord(env):
    env.writer.enabled = True
    item = env.item("a")
    state = env.runner.run(item)
    Path(state["draft"]["attachments"][1]).write_bytes(b"new PDF")
    state2 = env.runner.run(item, {"id": state["question"]["id"], "choice": "approve"})
    assert state2["question"]["id"] != state["question"]["id"]
    assert not env.mail.sent


def test_recette_reprise_le_lendemain(env):
    env.writer.enabled = True
    item = env.item("a", "recipe")
    state = env.runner.run(item)
    assert state["status"] == "recipe_ready"
    assert state["mail_status"] == "recipe_ready"
    env.clock = datetime(2026, 11, 24, 14, tzinfo=ZONE)
    env.reopen()
    assert env.runner.run(item)["status"] == "recipe_ready"
    preview = state["question"]
    assert preview["kind"] == "recipe_mail"
    approved = env.runner.run(item, {"id": preview["id"], "choice": "approve"})
    assert approved["mail_status"] == "recipe_ready"
    assert not approved["question"]
    assert not env.browser.receipts and not env.mail.sent
    assert env.runner.count(env.clock.date()) == 0


def test_codex_direct_reprend_le_depot_par_verification(env):
    item = env.item("direct")
    env.browser.native_submission = True

    def native_form(state, memory):
        recorded = env.runner.graph.get_state(config(item["dossier"])).values
        assert recorded["submission"] == state["submission"]
        assert recorded["submission"]["status"] == "open"
        env.browser.calls.append(("native", state["dossier"]))
        env.browser.receipts[state["dossier"]] = {"reference": state["dossier"]}
        raise Crash

    env.browser.run_form = native_form
    with pytest.raises(Crash):
        env.runner.run(item)
    env.reopen()
    assert env.runner.run(item)["status"] == "submitted"
    assert env.browser.calls == [("native", "direct"), ("verify", "direct")]


def test_attente_du_formulaire_direct_avant_toute_transmission(env):
    env.browser.native_submission = True
    item = env.item("direct")

    def native_form(state, memory):
        if not state.get("answers"):
            return {
                "kind": "question",
                "text": "Préavis ?",
                "transmission_attempted": False,
            }
        return {
            "kind": "submitted",
            "transmission_attempted": True,
            "receipt": {"reference": "direct"},
        }

    env.browser.run_form = native_form
    state = env.runner.run(item)
    assert state["submission"] is None
    answer = {"id": state["question"]["id"], "choice": "once", "text": "30 jours"}
    assert env.runner.run(item, answer)["status"] == "submitted"


def test_recette_garde_les_outils_de_transmission_fermes(env):
    env.browser.native_submission = True
    item = env.item("direct", "recipe")
    assert env.runner.run(item)["status"] == "recipe_ready"
    assert env.browser.calls == [("fill", "direct")]
