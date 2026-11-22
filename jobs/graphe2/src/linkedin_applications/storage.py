"""File d’exécution et mémoire privée. L’avancement du dossier reste dans LangGraph."""

import json
import os
import sqlite3
from contextlib import closing, contextmanager
from hashlib import sha256
from pathlib import Path

from .legacy_selection import retained_rows
from .urls import offer_url


@contextmanager
def database(path):
    with (
        closing(
            sqlite3.connect(
                path, timeout=10, uri=isinstance(path, str) and path.startswith("file:")
            )
        ) as db,
        db,
    ):
        db.row_factory = sqlite3.Row
        yield db


def selected(data, cycle):
    source = Path(data) / "discovery.sqlite3"
    with database(source.as_uri() + "?mode=ro") as db:
        if not db.execute("SELECT 1 FROM cycles WHERE id=?", (cycle,)).fetchone():
            raise ValueError("cycle_not_found")
        rows = list(retained_rows(db, cycle))
    dossiers = []
    for row in rows:
        offer = json.loads(row["content"])
        url = offer_url(offer.get("url"))
        if not url:
            continue
        uncertain = not row["human"] and json.loads(row["result"] or "{}").get(
            "incertitude", False
        )
        dossiers.append(
            {
                "dossier": sha256(url.encode()).hexdigest(),
                "offer": {**offer, "url": url},
                "version": row["id"],
                "cv": str(Path(data) / "snapshots" / (row["cv_hash"] + ".pdf")),
                "cv_hash": row["cv_hash"],
                "cv_text": row["cv_text"],
                "uncertain": bool(uncertain),
            }
        )
    return sorted(dossiers, key=lambda row: row["uncertain"])


class Queue:
    def __init__(self, data):
        self.data = Path(data)
        self.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.data / "queue.sqlite3"
        self.path.touch(mode=0o600, exist_ok=True)
        with database(self.path) as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS lots(
              id INTEGER PRIMARY KEY, cycle TEXT NOT NULL, mode TEXT NOT NULL, UNIQUE(cycle,mode)
            );
            CREATE TABLE IF NOT EXISTS items(
              lot INTEGER NOT NULL REFERENCES lots(id), dossier TEXT NOT NULL,
              position INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(lot,dossier)
            );
            """)

    def launch(self, data, cycle, mode, offer_keys=()):
        if mode not in {"recipe", "production"}:
            raise ValueError("mode_invalid")
        items = selected(data, cycle)
        if offer_keys:
            keys = set(offer_keys)
            if mode != "recipe" or not keys.issubset(
                item["offer"]["key"] for item in items
            ):
                raise ValueError("recipe_offers_invalid")
            items = [item for item in items if item["offer"]["key"] in keys]
        with database(self.path) as db:
            db.execute(
                "INSERT OR IGNORE INTO lots(cycle,mode) VALUES(?,?)", (cycle, mode)
            )
            lot = db.execute(
                "SELECT id FROM lots WHERE cycle=? AND mode=?", (cycle, mode)
            ).fetchone()[0]
            for position, item in enumerate(items):
                db.execute(
                    "INSERT OR IGNORE INTO items VALUES(?,?,?,?)",
                    (
                        lot,
                        item["dossier"],
                        position,
                        json.dumps({**item, "mode": mode}),
                    ),
                )
            return lot

    def items(self):
        with database(self.path) as db:
            return [
                json.loads(r[0])
                for r in db.execute("SELECT payload FROM items ORDER BY lot,position")
            ]


class Memory:
    def __init__(self, data, candidate_answers=None):
        self.candidate_answers = candidate_answers
        self.path = Path(data) / "reponses.md"

    def entries(self):
        if not self.path.exists():
            return []
        return [
            json.loads(line.removeprefix("- "))
            for line in self.path.read_text().splitlines()
            if line.startswith("- ")
        ]

    def read(self, state):
        offer = state["offer"]
        sql = self.candidate_answers.read(state) if self.candidate_answers else []
        return sql + [
            item
            for item in self.entries()
            if item["kind"] == "registration"
            or (
                not self.candidate_answers
                and (
                    item["dossier"] == state["dossier"]
                    or item["scope"] == "global"
                    or item["scope"] == f"company:{offer.get('company')}"
                )
            )
        ]

    def save(self, state, question, response):
        if self.candidate_answers and question["kind"] == "question":
            return
        items = self.entries()
        if any(item["id"] == question["id"] for item in items):
            return
        items.append(
            {
                **question,
                "dossier": state["dossier"],
                "answer": response.get("text", ""),
                "choice": response["choice"],
            }
        )
        temp = self.path.with_suffix(".tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write("# Réponses confirmées\n\n")
            for item in items:
                stream.write("- " + json.dumps(item, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(self.path)
