"""Capture and independently restore the private state of the two graphs."""

import argparse
import json
import os
import shutil
import sqlite3
import sys
from collections import Counter
from contextlib import ExitStack, closing
from hashlib import file_digest
from pathlib import Path
from tempfile import TemporaryDirectory

import ormsgpack


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def read_db(path, *, snapshot=False):
    options = "?mode=ro&immutable=1" if snapshot else "?mode=ro"
    return sqlite3.connect(path.resolve().as_uri() + options, uri=True)


def files(root):
    if root.is_symlink():
        raise ValueError("unexpected symlink")
    if root.is_file():
        yield root
    elif root.is_dir():
        for child in sorted(root.iterdir()):
            yield from files(child)
    else:
        raise ValueError("missing or unsupported file")


def inventory(discovery, applications, studio):
    result = {}
    for label, root, names in (
        ("discovery", discovery, ["discovery.sqlite3", "reports", "snapshots"]),
        ("applications", applications, ["queue.sqlite3", "checkpoints.sqlite3"]),
    ):
        optional = (
            ["validations", "dashboard.sqlite3"]
            if label == "discovery"
            else ["documents", "recette", "reponses.md"]
        )
        for name in names + [name for name in optional if (root / name).exists()]:
            for path in files(root / name):
                result[Path(label) / path.relative_to(root)] = path
    if studio:
        for path in files(studio):
            result[Path("studio") / path.relative_to(studio)] = path
    return result


def snapshot(discovery, applications, studio, dest):
    entries = inventory(discovery, applications, studio)
    with ExitStack() as stack:
        dbs = {}
        versions = {}
        hashes = {}
        for key, path in entries.items():
            if key.suffix == ".sqlite3":
                db = stack.enter_context(closing(read_db(path)))
                dbs[key] = db
                versions[key] = db.execute("PRAGMA data_version").fetchone()
            else:
                hashes[key] = digest(path)
        for key, source in entries.items():
            target = dest / key
            target.parent.mkdir(parents=True, exist_ok=True)
            if key in dbs:
                with closing(sqlite3.connect(target)) as clone:
                    dbs[key].backup(clone)
            else:
                shutil.copyfile(source, target)
                if digest(target) != hashes[key] or digest(source) != hashes[key]:
                    raise ValueError("source changed during capture")
        if (
            inventory(discovery, applications, studio) != entries
            or any(digest(entries[k]) != h for k, h in hashes.items())
            or any(
                db.execute("PRAGMA data_version").fetchone() != versions[k]
                for k, db in dbs.items()
            )
        ):
            raise ValueError("source changed during capture")


def manifest(root):
    return {str(p.relative_to(root)): digest(p) for p in files(root)}


def check_state(root):
    discovery = root / "discovery"
    applications = root / "applications"
    counts = {}
    for path in root.rglob("*.sqlite3"):
        with closing(read_db(path, snapshot=True)) as db:
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("SQLite integrity check failed")
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("SQLite foreign key check failed")
    with closing(read_db(discovery / "discovery.sqlite3", snapshot=True)) as db:
        for table in (
            "versions",
            "reports",
            "attempts",
            "attempt_responses",
            "reviews",
        ):
            counts["discovery_" + table] = db.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]
        counts["offers"] = db.execute(
            "SELECT count(DISTINCT offer_key) FROM versions"
        ).fetchone()[0]
        for name, expected in db.execute("SELECT path, sha256 FROM reports"):
            if digest(discovery / "reports" / Path(name).name) != expected:
                raise ValueError("report digest mismatch")
        for (expected,) in db.execute("SELECT DISTINCT cv_hash FROM cycles"):
            if digest(discovery / "snapshots" / (expected + ".pdf")) != expected:
                raise ValueError("CV digest mismatch")
        validations = list((discovery / "validations").glob("*.json"))
        counts["pilot_receipts"] = len(validations)
        for path in validations:
            receipt = json.loads(path.read_bytes())
            if not db.execute(
                "SELECT 1 FROM reports WHERE id=? AND sha256=?",
                (receipt["report_id"], receipt["report_sha256"]),
            ).fetchone():
                raise ValueError("validation report mismatch")
    with closing(read_db(applications / "queue.sqlite3", snapshot=True)) as db:
        dossiers = {row[0] for row in db.execute("SELECT DISTINCT dossier FROM items")}
        counts["lots"] = db.execute("SELECT count(*) FROM lots").fetchone()[0]
    latest = {}
    attempts, receipts, answers = set(), set(), set()
    with closing(read_db(applications / "checkpoints.sqlite3", snapshot=True)) as db:
        counts["checkpoints"] = db.execute(
            "SELECT count(*) FROM checkpoints"
        ).fetchone()[0]
        rows = db.execute(
            "SELECT thread_id, type, checkpoint FROM checkpoints "
            "WHERE checkpoint_ns='' ORDER BY checkpoint_id"
        )
        for thread, kind, blob in rows:
            if kind != "msgpack":
                raise ValueError("unsupported checkpoint encoding")
            state = ormsgpack.unpackb(blob, ext_hook=lambda code, value: None)[
                "channel_values"
            ]
            latest[thread] = state.get("status", "queued")
            for field in ("submission", "mail"):
                operation = state.get(field) or {}
                if operation:
                    key = (thread, field, operation["id"])
                    attempts.add(key)
                    if operation.get("receipt") or (
                        field == "submission" and state.get("evidence")
                    ):
                        receipts.add(key)
            for index, entry in enumerate(state.get("answers", [])):
                answers.add((thread, index, json.dumps(entry, sort_keys=True)))
            if (
                state.get("cv")
                and not (discovery / "snapshots" / Path(state["cv"]).name).is_file()
            ):
                raise ValueError("missing checkpoint CV")
            if state.get("letter"):
                parts = Path(state["letter"]).parts
                if (
                    "documents" not in parts
                    or not applications.joinpath(
                        *parts[parts.index("documents") :]
                    ).is_file()
                ):
                    raise ValueError("missing checkpoint letter")
    memory = applications / "reponses.md"
    counts["saved_answers"] = (
        sum(
            1
            for line in memory.read_text().splitlines()
            if line.startswith("- ") and isinstance(json.loads(line[2:]), dict)
        )
        if memory.exists()
        else 0
    )
    statuses = Counter(latest.get(key, "queued") for key in dossiers | latest.keys())
    allowed = {
        "waiting",
        "queued",
        "preparing",
        "ready",
        "recipe_ready",
        "blocked",
        "submitted",
        "deferred",
        "version_conflict",
        "submission_uncertain",
    }
    if statuses.keys() - allowed:
        raise ValueError("unknown dossier status")
    counts.update(
        dossier_status=dict(statuses),
        dossier_answers=len(answers),
        application_attempts=len(attempts),
        application_receipts=len(receipts),
        pdfs=sum(1 for _ in root.rglob("*.pdf")),
    )
    return counts


def restore(discovery, applications, studio, destination):
    roots = [discovery, applications] + ([studio] if studio else [])
    if any(destination.is_relative_to(root) for root in roots):
        raise ValueError("destination inside source")
    if destination.exists():
        raise FileExistsError("destination already exists")
    with TemporaryDirectory(dir=destination.parent) as tmp:
        stage = Path(tmp) / "bundle"
        reference, restored = stage / "reference", stage / "restored"
        snapshot(discovery, applications, studio, reference)
        expected = manifest(reference)
        shutil.copytree(reference, restored)
        if manifest(restored) != expected:
            raise ValueError("restore digest mismatch")
        counts = check_state(restored)
        counts["verified_files"] = len(expected)
        (stage / "sha256.json").write_text(json.dumps(expected, indent=2))
        (stage / "counts.json").write_text(json.dumps(counts, indent=2))
        # A concurrent run must never replace an earlier baseline.
        stage.rename(destination)
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("discovery", "applications", "destination", "studio", "verify"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.verify:
            if any((args.discovery, args.applications, args.destination, args.studio)):
                parser.error("--verify takes only the baseline directory")
            expected = json.loads((args.verify / "sha256.json").read_text())
            if any(
                manifest(args.verify / name) != expected
                for name in ("reference", "restored")
            ):
                raise ValueError("baseline digest mismatch")
            verified = check_state(args.verify / "restored")
            verified["verified_files"] = len(expected)
            if verified != json.loads((args.verify / "counts.json").read_text()):
                raise ValueError("baseline count mismatch")
            print(json.dumps(verified, sort_keys=True))
            sys.exit(0)
        if not all((args.discovery, args.applications, args.destination)):
            parser.error(
                "capture requires --discovery, --applications and --destination"
            )
        print(
            json.dumps(
                restore(
                    args.discovery.resolve(),
                    args.applications.resolve(),
                    args.studio.resolve() if args.studio else None,
                    args.destination.resolve(),
                ),
                sort_keys=True,
            )
        )
    except (ValueError, KeyError, OSError, sqlite3.Error) as error:
        sys.exit(f"Échec de la restauration ({type(error).__name__}).")
