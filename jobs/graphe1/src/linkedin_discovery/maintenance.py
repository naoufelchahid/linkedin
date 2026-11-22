"""Sauvegarde cohérente et restauration de contrôle de l’état privé."""

import hashlib
import io
import json
import os
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


def verify_backup(archive):
    try:
        with tarfile.open(archive, "r:gz") as tar, tempfile.TemporaryDirectory() as temp:
            members = tar.getmembers()
            names = [member.name for member in members]
            if len(names) != len(set(names)) or "manifest.json" not in names:
                raise ValueError("invalid manifest")
            for member in members:
                path = PurePosixPath(member.name)
                if not member.isfile() or path.is_absolute() or ".." in path.parts:
                    raise ValueError("unsafe archive member")
            manifest = json.load(tar.extractfile("manifest.json"))
            records = manifest["files"]
            if set(names) != {"manifest.json", *(r["path"] for r in records)}:
                raise ValueError("archive manifest mismatch")
            for record in records:
                content = tar.extractfile(record["path"]).read()
                if hashlib.sha256(content).hexdigest() != record["sha256"]:
                    raise ValueError("checksum mismatch")
                if record["path"].endswith(".sqlite3"):
                    target = Path(temp) / record["path"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                    db = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
                    try:
                        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise ValueError("database integrity failed")
                    finally:
                        db.close()
        return {
            "status": "verified",
            "archive": str(Path(archive).resolve()),
            "files": len(records),
        }
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, sqlite3.Error):
        raise ValueError("backup_integrity_failed") from None


def backup_state(store, destination):
    destination = Path(destination).resolve()
    if destination.is_relative_to(store.data.resolve()):
        raise ValueError("backup_destination_inside_state")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    archive = destination / f"discovery-{stamp}.tar.gz"
    temporary = archive.with_suffix(".partial")
    records = []
    with store.locked(), tempfile.TemporaryDirectory() as temp:
        with tarfile.open(temporary, "w:gz") as tar:
            os.chmod(temporary, 0o600)
            for source in sorted(store.data.rglob("*")):
                relative = source.relative_to(store.data)
                if source.is_symlink() or not source.is_file():
                    continue
                if "qualifier" in relative.parts or source.name.endswith(
                    (".lock", "-wal", "-shm", "-journal")
                ):
                    continue
                if source.suffix == ".sqlite3":
                    snapshot_path = Path(temp) / relative
                    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                    with (
                        closing(
                            sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
                        ) as db,
                        closing(sqlite3.connect(snapshot_path)) as snapshot,
                    ):
                        db.backup(snapshot)
                    content = snapshot_path.read_bytes()
                else:
                    content = source.read_bytes()
                info = tarfile.TarInfo(relative.as_posix())
                info.size, info.mode = len(content), 0o600
                tar.addfile(info, io.BytesIO(content))
                records.append(
                    {"path": relative.as_posix(), "sha256": hashlib.sha256(content).hexdigest()}
                )
            manifest = json.dumps(
                {"format": 1, "created_at": stamp, "files": records}, ensure_ascii=False
            ).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size, info.mode = len(manifest), 0o600
            tar.addfile(info, io.BytesIO(manifest))
    verify_backup(temporary)
    temporary.rename(archive)
    return verify_backup(archive)
