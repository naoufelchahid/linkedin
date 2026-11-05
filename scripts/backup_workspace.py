#!/usr/bin/env python3
"""Sauvegarde locale privée des deux processus, puis restauration de contrôle."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.git', 'backups', 'tmp', '__pycache__', '.pytest_cache', '.playwright-mcp', '.venv'}


def verify(folder):
    manifest = json.loads((folder / 'manifest.json').read_text())
    with tempfile.TemporaryDirectory(prefix='linkedin-restore-') as temp:
        restored = Path(temp)
        with tarfile.open(folder / 'workspace.tar.gz', 'r:gz') as tar:
            for member in tar.getmembers():
                name = Path(member.name)
                if not member.isfile() or name.is_absolute() or '..' in name.parts:
                    raise ValueError('backup_unsafe_member')
                target = restored / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source:
                    target.write_bytes(source.read())
        for record in manifest['files']:
            path = restored / record['path']
            if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
                raise ValueError('backup_checksum_mismatch')
            if path.suffix == '.sqlite3':
                db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
                try:
                    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('backup_database_corrupted')
                finally:
                    db.close()
    return len(manifest['files'])


def backup(root=ROOT):
    os.umask(0o077)
    dest = root / 'backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    dest.mkdir(parents=True, mode=0o700)
    dest.parent.chmod(0o700)
    records = []
    with tempfile.TemporaryDirectory(prefix='linkedin-snapshots-') as temp:
        with tarfile.open(dest / 'workspace.tar.gz', 'w:gz') as tar:
            for path in sorted(root.rglob('*')):
                rel = path.relative_to(root)
                if any(part in EXCLUDED for part in rel.parts) or path.is_symlink() or not path.is_file():
                    continue
                if path.name.endswith(('-wal', '-shm', '.lock', '.pyc')):
                    continue
                source = path
                if path.suffix == '.sqlite3':
                    source = Path(temp) / str(len(records))
                    db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
                    snapshot = sqlite3.connect(source)
                    try:
                        db.backup(snapshot)
                    finally:
                        snapshot.close()
                        db.close()
                # Copie figée avant l'ajout au tar et son empreinte.
                data = source.read_bytes()
                import io
                info = tarfile.TarInfo(str(rel))
                info.size = len(data)
                info.mode = 0o600
                tar.addfile(info, io.BytesIO(data))
                records.append({'path': str(rel), 'sha256': hashlib.sha256(data).hexdigest()})
    (dest / 'manifest.json').write_text(json.dumps({'created_at': datetime.now(timezone.utc).isoformat(),
                                                 'files': records}, indent=2) + '\n')
    count = verify(dest)
    return dest, count


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', type=Path, help='Restaurer et vérifier une sauvegarde existante, sans modifier le projet')
    args = parser.parse_args()
    os.umask(0o077)
    if args.verify:
        print(f'Restauration temporaire vérifiée : {verify(args.verify)} fichiers.')
    else:
        dest, count = backup()
        print(f'Sauvegarde privée : {dest}\nRestauration temporaire vérifiée : {count} fichiers.')
