"""État durable propre au pilote ; snapshots et rapports immuables."""

import fcntl
import json
import os
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path

from .adapters.pdf import extract_text
from .documents import freeze_cv_in
from .model import digest, dump, now, offer_url
from .postgres_import import insert_offer
from .postgres_store import PostgresConnection

SCHEMA = files("linkedin_discovery.resources").joinpath("schema.sql").read_text(encoding="utf-8")


class Store:
    def __init__(self, data, postgres_dsn=None):
        self.postgres_dsn = postgres_dsn
        self.data = Path(data)
        self.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.data.chmod(0o700)
        self._lock_depth = 0
        if postgres_dsn:
            self.db = PostgresConnection(postgres_dsn)
            return
        path = self.data / "discovery.sqlite3"
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        path.chmod(0o600)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.create_function("offer_url", 1, offer_url, deterministic=True)
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self.db.close()
            raise RuntimeError("database_schema_version_unsupported")
        self.db.executescript(SCHEMA)
        self.db.execute("PRAGMA user_version=1")

    def close(self):
        self.db.close()

    @contextmanager
    def locked(self):
        if self._lock_depth:
            self._lock_depth += 1
            try:
                yield
            finally:
                self._lock_depth -= 1
            return
        with (self.data / "execution.lock").open("a") as stream:
            os.chmod(stream.name, 0o600)
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("discovery_already_running") from None
            try:
                if (
                    self.postgres_dsn
                    and not self.db.execute(
                        "SELECT pg_try_advisory_lock(1765839006) AS acquired"
                    ).fetchone()["acquired"]
                ):
                    raise RuntimeError("discovery_already_running")
                self._lock_depth = 1
                yield
            finally:
                if self._lock_depth and self.postgres_dsn:
                    self.db.execute("SELECT pg_advisory_unlock(1765839006)")
                self._lock_depth = 0
                fcntl.flock(stream, fcntl.LOCK_UN)

    def transaction(self):
        return self.db.transaction() if self.postgres_dsn else self.db

    def execute(self, sql, args=()):
        with self.transaction():
            return self.db.execute(sql, args)

    def cycle(self, ident):
        row = self.db.execute("SELECT * FROM cycles WHERE id=?", (ident,)).fetchone()
        if row is None:
            raise ValueError("cycle_not_found")
        return dict(row)

    def create_cycle(self, cv_bytes, cv_text, prompt, settings, ident=None, provenance="provided"):
        ident = ident or uuid.uuid4().hex
        cv_hash = digest(cv_bytes)
        snapshots = self.data / "snapshots"
        snapshots.mkdir(exist_ok=True, mode=0o700)
        cv_path = snapshots / (cv_hash + ".pdf")
        if not cv_path.exists():
            with tempfile.NamedTemporaryFile(dir=snapshots) as stream:
                stream.write(cv_bytes)
                stream.flush()
                os.fsync(stream.fileno())
                stream.seek(0)
                if digest(stream.read()) != cv_hash:
                    raise ValueError("saved_cv_integrity_failed")
                try:
                    os.link(stream.name, cv_path)
                except FileExistsError:
                    pass  # Un autre cycle a publié le même snapshot.
        if digest(cv_path.read_bytes()) != cv_hash:
            raise ValueError("saved_cv_integrity_failed")
        if cv_text is None and not self.postgres_dsn:
            cv_text = extract_text(cv_bytes)
        # L’association documentaire et le cycle partagent la transaction PostgreSQL.
        # Une panne de publication annule le cycle avant toute collecte.
        with self.transaction():
            self.db.execute(
                """INSERT INTO cycles(id,created_at,cv_hash,cv_text,prompt_hash,prompt,settings)
                   VALUES(?,?,?,?,?,?,?)""",
                (ident, now(), cv_hash, cv_text or "", digest(prompt), prompt, dump(settings)),
            )
            if self.postgres_dsn:
                markdown = freeze_cv_in(self.db.connection, ident, cv_bytes, cv_text, provenance)
                self.db.execute("UPDATE cycles SET cv_text=? WHERE id=?", (markdown, ident))
        return ident

    def ingest(self, cycle_id, profile, raw, offer=None, error=""):
        if self.postgres_dsn:
            with self.transaction():
                if offer and offer["url"] and profile != "review-replay":
                    first = self.db.execute(
                        """SELECT v.offer_key FROM occurrences o JOIN versions v ON v.id=o.version_id
                           WHERE o.canonical_url=? ORDER BY o.observed_at,v.id LIMIT 1""",
                        (offer["url"],),
                    ).fetchone()
                    if first:
                        offer = {**offer, "key": first["offer_key"]}
                with self.db.connection.cursor() as cursor:
                    payload = self.db.execute(
                        "SELECT ?::jsonb::text AS raw", (dump(raw),)
                    ).fetchone()["raw"]
                    version, _ = insert_offer(cursor, cycle_id, profile, raw, payload, offer or {})
                return version
        raw_hash = digest(dump(raw))
        version_id = None
        with self.transaction():
            if offer:
                if offer["url"] and profile != "review-replay":
                    first = self.db.execute(
                        """SELECT offer_key FROM versions
                           WHERE offer_url(json_extract(content,'$.url'))=?
                           ORDER BY created_at,id LIMIT 1""",
                        (offer["url"],),
                    ).fetchone()
                    if first:
                        offer = {**offer, "key": first["offer_key"]}
                content = dump(offer)
                version_id = digest(content)
                self.db.execute(
                    "INSERT OR IGNORE INTO versions VALUES(?,?,?,?,?)",
                    (version_id, offer["key"], digest(content), content, now()),
                )
            self.db.execute(
                "INSERT INTO occurrences VALUES(?,?,?,?,?,?,?) ON CONFLICT(cycle_id,profile,raw_hash) DO UPDATE SET version_id=excluded.version_id,error=excluded.error,observed_at=excluded.observed_at",
                (cycle_id, profile, raw_hash, dump(raw), version_id, error, now()),
            )
        return version_id

    def pending_versions(self, cycle_id):
        rows = self.db.execute(
            "SELECT v.* FROM versions v JOIN occurrences o ON o.version_id=v.id WHERE o.cycle_id=? ORDER BY o.observed_at",
            (cycle_id,),
        ).fetchall()
        latest = {
            offer_url(json.loads(row["content"])["url"]) or row["offer_key"]: row for row in rows
        }
        return list(latest.values())

    def qualification(self, cycle, version_id):
        ident = digest(dump([version_id, cycle["cv_hash"], cycle["prompt_hash"]]))
        self.execute(
            """DELETE FROM cycle_items WHERE cycle_id=? AND version_id<>? AND version_id IN
            (SELECT id FROM versions WHERE offer_key=(SELECT offer_key FROM versions WHERE id=?))""",
            (cycle["id"], version_id, version_id),
        )
        self.execute(
            "INSERT INTO qualifications(id,version_id,cv_hash,prompt_hash,status) VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING",
            (ident, version_id, cycle["cv_hash"], cycle["prompt_hash"], "pending"),
        )
        self.execute(
            "INSERT INTO cycle_items VALUES(?,?,?) ON CONFLICT(cycle_id,version_id) DO UPDATE SET qualification_id=excluded.qualification_id",
            (cycle["id"], version_id, ident),
        )
        return dict(self.db.execute("SELECT * FROM qualifications WHERE id=?", (ident,)).fetchone())

    def mark_unreadable(self, qualification_id):
        self.execute(
            "UPDATE qualifications SET status='data_problem',error='announcement_or_cv_unreadable' WHERE id=?",
            (qualification_id,),
        )

    def start_attempt(self, qualification_id):
        # Une tentative interrompue consomme le budget ; aucun envoi métier ici.
        self.execute(
            "UPDATE attempts SET status='interrupted',error='process_interrupted',finished_at=? WHERE qualification_id=? AND status='running'",
            (now(), qualification_id),
        )
        number = (
            self.db.execute(
                "SELECT count(*) AS total FROM attempts WHERE qualification_id=?",
                (qualification_id,),
            ).fetchone()["total"]
            + 1
        )
        if number > 3:
            self.execute(
                "UPDATE qualifications SET status='error',error='qualification_attempts_exhausted' WHERE id=?",
                (qualification_id,),
            )
            return None
        self.execute(
            "INSERT INTO attempts(qualification_id,number,status,started_at) VALUES(?,?,?,?)",
            (qualification_id, number, "running", now()),
        )
        return number

    def finish_attempt(self, qualification_id, number, result=None, error="", rejected_result=None):
        status = (
            "data_problem"
            if result and result["verdict"] is None
            else "done"
            if result
            else "error"
        )
        with self.transaction():
            if rejected_result is not None:
                self.db.execute(
                    "INSERT INTO attempt_responses VALUES(?,?,?) ON CONFLICT(qualification_id,number) DO UPDATE SET response=excluded.response",
                    (qualification_id, number, dump(rejected_result)),
                )
            self.db.execute(
                "UPDATE attempts SET status=?,error=?,finished_at=? WHERE qualification_id=? AND number=?",
                (status, error, now(), qualification_id, number),
            )
            self.db.execute(
                "UPDATE qualifications SET status=?,result=?,error=? WHERE id=?",
                (status, dump(result) if result else None, error, qualification_id),
            )

    def items(self, cycle_id):
        rows = self.db.execute(
            """SELECT v.id version_id,v.content,q.id qualification_id,q.status,q.result,q.error
            FROM cycle_items i JOIN versions v ON v.id=i.version_id
            JOIN qualifications q ON q.id=i.qualification_id WHERE i.cycle_id=?""",
            (cycle_id,),
        )
        items = []
        for row in rows:
            item = dict(row)
            item["offer"] = json.loads(item.pop("content"))
            item["result"] = json.loads(item["result"]) if item["result"] else None
            # Correction humaine attachée à la version de l'annonce, jamais au titre.
            review = self.db.execute(
                "SELECT verdict,note FROM reviews WHERE version_id=? ORDER BY id DESC LIMIT 1",
                (item["version_id"],),
            ).fetchone()
            item["human_verdict"] = review["verdict"] if review else None
            item["effective_verdict"] = item["human_verdict"] or (item["result"] or {}).get(
                "verdict"
            )
            items.append(item)
        return items

    def review(self, report_id, number, verdict, note=""):
        if verdict not in ("retenir", "écarter"):
            raise ValueError("invalid_human_verdict")
        item = self.db.execute(
            "SELECT * FROM review_items WHERE report_id=? AND number=?", (report_id, number)
        ).fetchone()
        if item is None:
            raise ValueError("report_item_not_found")
        self.execute(
            "INSERT INTO reviews(report_id,number,version_id,verdict,note,created_at) VALUES(?,?,?,?,?,?)",
            (report_id, number, item["version_id"], verdict, note, now()),
        )

    def validate_report(self, report_id):
        if not self.db.execute("SELECT id FROM reports WHERE id=?", (report_id,)).fetchone():
            raise ValueError("report_not_found")
        self.execute(
            "INSERT INTO pilot_validations(report_id,created_at) VALUES(?,?) ON CONFLICT DO NOTHING",
            (report_id, now()),
        )

    def event(self, cycle_id, step, status, duration, technical_id=""):
        self.execute(
            "INSERT INTO events(cycle_id,step,status,duration,created_at,technical_id) VALUES(?,?,?,?,?,?)",
            (cycle_id, step, status, duration, now(), technical_id),
        )
