"""Graphe 1 : collecte, qualification et rapport, avec reprise SQLite."""

import json
import time
import uuid
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import psycopg
from jsonschema import ValidationError
from langchain_core.tracers.langchain import wait_for_all_tracers
from langgraph.checkpoint.postgres import PostgresSaver
from langsmith import Client, trace, tracing_context
from psycopg.rows import dict_row

from .adapters.pdf import read_pdf
from .collection import attach_profile_run, start_profile_run
from .connectors import Apify, Codex, ConnectorError
from .documents import cycle_cv
from .graph import build_graph
from .model import checked_result, digest, normalize
from .prompts import qualification_prompt
from .report import make_report, restore_report
from .store import Store


class DiscoveryService:
    def __init__(self, config, *, apify=None, codex=None):
        self.config = config
        self.store = Store(config.data, config.postgres_dsn)
        self.apify = apify or Apify(config.token, config.actor)
        self.codex = codex or Codex(config.data, config.codex_seconds)
        self.tracer = (
            Client(
                api_key=config.langsmith_key,
                api_url=config.langsmith_endpoint,
                hide_inputs=not config.langsmith_trace_content,
                hide_outputs=not config.langsmith_trace_content,
            )
            if config.langsmith_key
            else None
        )

    def daily_cycle(self):
        """Sous le verrou : une seule collecte planifiée par jour de Casablanca."""
        today = datetime.now(ZoneInfo("Africa/Casablanca")).date().isoformat()
        for row in self.store.db.execute("SELECT id,settings FROM cycles ORDER BY created_at DESC"):
            if json.loads(row["settings"]).get("schedule_date") == today:
                return row["id"]
        ident = self.create()
        settings = json.loads(self.store.cycle(ident)["settings"])
        settings["schedule_date"] = today
        self.store.execute("UPDATE cycles SET settings=? WHERE id=?", (json.dumps(settings), ident))
        return ident

    def status(self, cycle_id=None):
        if cycle_id is None:
            row = self.store.db.execute(
                "SELECT id FROM cycles ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return {"status": "empty", "cycles": 0}
            cycle_id = row["id"]
        cycle = self.store.cycle(cycle_id)
        counts = self.store.db.execute(
            """SELECT q.status,count(*) total FROM qualifications q
            JOIN cycle_items i ON i.qualification_id=q.id WHERE i.cycle_id=? GROUP BY q.status""",
            (cycle_id,),
        )
        report = self.store.db.execute(
            "SELECT id,path FROM reports WHERE cycle_id=? ORDER BY created_at DESC LIMIT 1",
            (cycle_id,),
        ).fetchone()
        return dict(
            cycle_id=cycle_id,
            status=cycle["status"],
            created_at=cycle["created_at"],
            qualifications={r["status"]: r["total"] for r in counts},
            report=dict(report) if report else None,
        )

    def compare(self, report_id, cycle_id):
        row = self.store.db.execute(
            "SELECT snapshot FROM reports WHERE id=?", (report_id,)
        ).fetchone()
        if row is None:
            raise ValueError("report_not_found")
        self.store.cycle(cycle_id)
        snapshot = json.loads(row["snapshot"])
        items = {i["version_id"]: i for i in self.store.items(cycle_id)}
        comparisons = []
        for n, item in enumerate(snapshot["selected"], 1):
            human = self.store.db.execute(
                "SELECT verdict FROM reviews WHERE report_id=? AND number=? ORDER BY id DESC LIMIT 1",
                (report_id, n),
            ).fetchone()
            verdict = (items.get(item["version_id"], {}).get("result") or {}).get("verdict")
            comparisons.append(
                dict(
                    number=n,
                    human=human["verdict"] if human else None,
                    codex=verdict,
                    agrees=verdict == human["verdict"] if human and verdict else None,
                )
            )
        return dict(report_id=report_id, cycle_id=cycle_id, comparisons=comparisons)

    def attach_run(self, cycle_id, profile, run_id):
        cycle = self.store.cycle(cycle_id)
        settings = json.loads(cycle["settings"])
        attach_profile_run(self.store, self.apify, cycle_id, profile, run_id, settings)
        return dict(status="attached", cycle_id=cycle_id, run_id=run_id)

    def create(self, *, cv_data=None, prompt=None, replay_of=None, search=None, ident=None):
        cv_bytes, cv_text = cv_data if cv_data else (read_pdf(self.config.cv), None)
        settings = dict(
            profiles=search.profiles if search else list(self.config.profiles),
            limit=search.limit if search else self.config.limit,
            collect_seconds=self.config.collect_seconds,
            actor=self.config.actor,
            source="replay" if replay_of else "apify",
            replay_of=replay_of,
        )
        if search:
            settings.update(location=search.location, period=search.period)
        ident = self.store.create_cycle(
            cv_bytes,
            cv_text,
            prompt or qualification_prompt(prompt_file=self.config.prompt_file),
            settings,
            ident=ident,
            provenance="provided" if cv_data else f"DISCOVERY_CV/{self.config.cv.name}",
        )
        if replay_of:
            # Rejeu sur les données déjà sauvegardées, sans nouvel appel Apify.
            self.store.cycle(replay_of)
            for row in self.store.db.execute(
                "SELECT profile,raw FROM occurrences WHERE cycle_id=?", (replay_of,)
            ).fetchall():
                self.ingest(ident, row["profile"], json.loads(row["raw"]))
        return ident

    def replay(self, report_id, prompt=None):
        row = self.store.db.execute(
            "SELECT snapshot FROM reports WHERE id=?", (report_id,)
        ).fetchone()
        if row is None:
            raise ValueError("report_not_found")
        snapshot = json.loads(row["snapshot"])
        original = self.store.cycle(snapshot["cycle_id"])
        saved = (
            cycle_cv(self.config.postgres_dsn, original["id"]) if self.config.postgres_dsn else None
        )
        if saved:
            content, markdown = saved
        else:
            content = (self.store.data / "snapshots" / (original["cv_hash"] + ".pdf")).read_bytes()
            markdown = original["cv_text"]
        if digest(content) != original["cv_hash"]:
            raise ValueError("saved_cv_integrity_failed")
        settings = json.loads(original["settings"])
        settings.update(source="replay", replay_of=original["id"], report_id=report_id)
        ident = self.store.create_cycle(
            content,
            markdown,
            prompt or qualification_prompt(prompt_file=self.config.prompt_file),
            settings,
            provenance=f"replay/{original['id']}",
            text_is_frozen=True,
        )
        for item in snapshot["selected"]:
            self.store.ingest(ident, "review-replay", item["offer"], offer=item["offer"])
        return ident

    @contextmanager
    def step(self, cycle_id, name, technical_id=""):
        started = time.monotonic()
        start_time = datetime.now(timezone.utc)
        status = "completed"
        try:
            yield
        except BaseException:
            status = "error"
            raise
        finally:
            duration = time.monotonic() - started
            self.store.event(cycle_id, name, status, duration, technical_id)
            if self.tracer and not self.config.langsmith_trace_content:
                try:
                    self.tracer.create_run(
                        id=uuid.uuid4(),
                        name=name,
                        run_type="chain",
                        inputs={},
                        outputs={},
                        start_time=start_time,
                        end_time=datetime.now(timezone.utc),
                        project_name=self.config.langsmith_project,
                        extra={
                            "metadata": dict(
                                cycle_id=cycle_id,
                                technical_id=technical_id,
                                status=status,
                                duration_seconds=duration,
                            )
                        },
                    )
                except Exception:
                    self.store.event(cycle_id, "langsmith", "unavailable", 0)

    def ingest(self, cycle_id, profile, raw):
        try:
            offer = normalize(raw)
        except (ValueError, TypeError):
            return self.store.ingest(cycle_id, profile, raw, error="announcement_unusable")
        return self.store.ingest(cycle_id, profile, raw, offer)

    def collect(self, state):
        ident = state["cycle_id"]
        cycle = self.store.cycle(ident)
        settings = json.loads(cycle["settings"])
        if settings["source"] == "replay":
            self.store.execute("UPDATE cycles SET status='replay' WHERE id=?", (ident,))
            return {"collection": self.collection_summary(ident)}
        if self.config.postgres_dsn and cycle["status"] == "collected":
            return {"collection": self.collection_summary(ident)}
        with self.step(ident, "collect"):
            for profile in settings["profiles"]:
                start_profile_run(self.store, self.apify, ident, profile, settings)
            age = (
                datetime.now(timezone.utc) - datetime.fromisoformat(cycle["created_at"])
            ).total_seconds()
            deadline = time.monotonic() + max(0, settings["collect_seconds"] - age)
            while True:
                active = False
                rows = self.store.db.execute(
                    "SELECT * FROM runs WHERE cycle_id=?", (ident,)
                ).fetchall()
                for row in rows:
                    if not row["run_id"]:
                        continue
                    try:
                        run = self.apify.run(row["run_id"])
                        status = run["status"]
                        dataset = run.get("defaultDatasetId") or row["dataset_id"]
                        error = (
                            ""
                            if status in ("SUCCEEDED", "RUNNING", "READY")
                            else "apify_run_" + status.lower()
                        )
                        self.store.execute(
                            "UPDATE runs SET status=?,dataset_id=?,error=? WHERE cycle_id=? AND profile=?",
                            (status, dataset, error, ident, row["profile"]),
                        )
                        active |= status not in Apify.TERMINAL
                    except (ConnectorError, KeyError, TypeError):
                        active = True
                        self.store.execute(
                            "UPDATE runs SET error='apify_poll_failed' WHERE cycle_id=? AND profile=?",
                            (ident, row["profile"]),
                        )
                if not active or time.monotonic() >= deadline:
                    break
                time.sleep(min(self.config.poll_seconds, max(0, deadline - time.monotonic())))
            # Lire aussi les datasets partiels ; un resume récupérera la suite.
            for row in self.store.db.execute(
                "SELECT * FROM runs WHERE cycle_id=?", (ident,)
            ).fetchall():
                if not row["dataset_id"]:
                    continue
                try:
                    for raw in self.apify.items(row["dataset_id"], settings["limit"]):
                        self.ingest(ident, row["profile"], raw)
                except ConnectorError:
                    self.store.execute(
                        "UPDATE runs SET error='apify_dataset_failed' WHERE cycle_id=? AND profile=?",
                        (ident, row["profile"]),
                    )
            rows = self.store.db.execute(
                "SELECT status,error FROM runs WHERE cycle_id=?", (ident,)
            ).fetchall()
            complete = bool(rows) and all(
                r["status"] == "SUCCEEDED" and not r["error"] for r in rows
            )
            self.store.execute(
                "UPDATE cycles SET status=? WHERE id=?",
                ("collected" if complete else "partial", ident),
            )
        return {"collection": self.collection_summary(ident)}

    def collection_summary(self, cycle_id):
        cycle = self.store.cycle(cycle_id)
        settings = json.loads(cycle["settings"])
        return dict(
            source=settings["source"],
            profiles=settings["profiles"],
            limit=settings["limit"],
            offers=self.store.db.execute(
                "SELECT count(*) AS total FROM occurrences WHERE cycle_id=?", (cycle_id,)
            ).fetchone()["total"],
            runs=[
                dict(row)
                for row in self.store.db.execute(
                    "SELECT profile,run_id,status,error FROM runs WHERE cycle_id=?", (cycle_id,)
                )
            ],
        )

    def qualification_trace(self, cycle, offer, qualification_id, *, cached=False):
        if not self.config.langsmith_trace_content or not self.tracer:
            return nullcontext()
        return trace(
            "qualification.cache" if cached else "codex.qualification",
            run_type="chain" if cached else "llm",
            inputs={"annonce": offer, "cv": cycle["cv_text"], "prompt": cycle["prompt"]},
            metadata={
                "cycle_id": cycle["id"],
                "qualification_id": qualification_id,
                "cached": cached,
            },
            client=self.tracer,
            project_name=self.config.langsmith_project,
        )

    def qualify(self, state):
        cycle = self.store.cycle(state["cycle_id"])
        with self.step(cycle["id"], "qualify"):
            for version in self.store.pending_versions(cycle["id"]):
                offer = json.loads(version["content"])
                q = self.store.qualification(cycle, version["id"])
                if q["status"] in ("done", "data_problem"):
                    with self.qualification_trace(cycle, offer, q["id"], cached=True) as span:
                        if span:
                            span.end(outputs={"result": json.loads(q["result"] or "null")})
                    continue
                if not offer["description"].strip() or not cycle["cv_text"].strip():
                    self.store.mark_unreadable(q["id"])
                    continue
                while True:
                    number = self.store.start_attempt(q["id"])
                    if number is None:
                        break
                    result = None
                    try:
                        with self.step(cycle["id"], "codex_attempt", q["id"]):
                            with self.qualification_trace(cycle, offer, q["id"]) as span:
                                result = self.codex.qualify(
                                    offer, cycle["cv_text"], cycle["prompt"]
                                )
                                checked_result(result, offer, cycle["cv_text"])
                                if span:
                                    span.end(outputs={"result": result})
                        self.store.finish_attempt(q["id"], number, result=result)
                        break
                    except (
                        ConnectorError,
                        ValidationError,
                        ValueError,
                        TypeError,
                        KeyError,
                        OSError,
                    ) as exc:
                        safe_codes = {
                            "qualification_identity_or_reason_invalid",
                            "data_problem_missing",
                            "data_problem_with_verdict",
                            "mission_quote_not_in_announcement",
                            "skill_quote_not_in_cv",
                            "evidence_missing",
                        }
                        code = (
                            str(exc)
                            if (type(exc) is ValueError and str(exc) in safe_codes)
                            or isinstance(exc, ConnectorError)
                            else "codex_or_schema_failed"
                        )
                        self.store.finish_attempt(
                            q["id"], number, error=code, rejected_result=result
                        )
        return {"qualification_counts": self.status(cycle["id"])["qualifications"]}

    def report(self, state):
        with self.step(state["cycle_id"], "report"):
            report_id, path = make_report(
                self.store,
                state["cycle_id"],
                state.get("report_id") if self.config.postgres_dsn else None,
            )
        return dict(
            report_id=report_id,
            report_path=str(path),
            status=self.store.cycle(state["cycle_id"])["status"],
        )

    def graph(self):
        return build_graph(self)

    def run(self, cycle_id):
        try:
            with self.store.locked(), self.tracing(cycle_id):
                if self.config.postgres_dsn:
                    return self._run_postgres(cycle_id)
                return self.graph().invoke(
                    {"cycle_id": cycle_id}, {"run_name": "graphe1.discovery"}
                )
        finally:
            self.flush_traces()

    def _run_postgres(self, cycle_id):
        cycle = self.store.cycle(cycle_id)
        config = {"run_name": "graphe1.discovery", "configurable": {"thread_id": cycle_id}}
        with psycopg.connect(self.config.postgres_dsn, autocommit=True, row_factory=dict_row) as db:
            db.execute("SET search_path TO pg_catalog, runtime_g1")

            def checkpoint_report(state):
                result = self.report(state)
                return {"report_id": result["report_id"], "status": result["status"]}

            graph = build_graph(self, PostgresSaver(db), report_node=checkpoint_report)
            checkpoint = graph.get_state(config)
            if checkpoint.next:
                # LangGraph reprend les tâches restantes du fil, y compris leurs écritures durables.
                state = graph.invoke(None, config, durability="sync")
            elif checkpoint.values and cycle["status"] != "partial":
                state = dict(checkpoint.values)
            else:
                # Nouveau fil ou collecte partielle : reprendre les runs Apify enregistrés.
                # Réserver la référence du rapport avant sa transaction SQL.
                report_id = uuid.uuid4().hex
                if not checkpoint.values and cycle["status"] in ("collected", "replay"):
                    previous = self.status(cycle_id)["report"]
                    if previous:
                        report_id = previous["id"]
                state = graph.invoke(
                    {"cycle_id": cycle_id, "report_id": report_id}, config, durability="sync"
                )
        path = restore_report(self.store, cycle_id, state["report_id"])
        if path is None:
            raise ValueError("report_not_found")
        return {**state, "report_path": str(path)}

    def tracing(self, cycle_id):
        return tracing_context(
            enabled=bool(self.tracer and self.config.langsmith_trace_content),
            client=self.tracer,
            project_name=self.config.langsmith_project,
            metadata={"cycle_id": cycle_id, "thread_id": cycle_id},
            tags=["graphe1"],
        )

    def flush_traces(self):
        if isinstance(self.tracer, Client):
            wait_for_all_tracers()
            self.tracer.flush(timeout=10)


# Alias de compatibilité pour les intégrations du pilote validé.
Pilot = DiscoveryService
