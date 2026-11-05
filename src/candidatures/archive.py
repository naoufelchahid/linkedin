"""Historique transactionnel et exports privés, sans action distante."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3


def install_history(db):
    """Les triggers couvrent aussi les mises à jour faites par le poller Telegram."""
    db.executescript('''
      BEGIN IMMEDIATE;
      CREATE TABLE IF NOT EXISTS case_versions (
        case_id TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL,
        cv_hash TEXT NOT NULL, digest TEXT NOT NULL, captured_at TEXT NOT NULL,
        origin TEXT NOT NULL, PRIMARY KEY(case_id, version)
      );
      CREATE TABLE IF NOT EXISTS case_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, version INTEGER NOT NULL,
        state TEXT NOT NULL, approved_at TEXT, expires_at TEXT, approval_hash TEXT,
        receipt TEXT, last_error TEXT, captured_at TEXT NOT NULL, origin TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS cv_snapshots (
        sha256 TEXT PRIMARY KEY, content BLOB NOT NULL, captured_at TEXT NOT NULL
      );
      INSERT OR IGNORE INTO case_versions
        SELECT id,version,payload,cv_hash,digest,strftime('%Y-%m-%dT%H:%M:%fZ','now'),
          'migration_current_only' FROM cases;
      INSERT INTO case_events(case_id,version,state,approved_at,expires_at,approval_hash,
                              receipt,last_error,captured_at,origin)
        SELECT id,version,state,approved_at,expires_at,approval_hash,receipt,last_error,
          strftime('%Y-%m-%dT%H:%M:%fZ','now'),'migration_current_only' FROM cases c
        WHERE NOT EXISTS (SELECT 1 FROM case_events e WHERE e.case_id=c.id);
      CREATE TRIGGER IF NOT EXISTS archive_case_insert AFTER INSERT ON cases BEGIN
        INSERT INTO case_versions VALUES (NEW.id,NEW.version,NEW.payload,NEW.cv_hash,NEW.digest,
          strftime('%Y-%m-%dT%H:%M:%fZ','now'),'live');
        INSERT INTO case_events(case_id,version,state,approved_at,expires_at,approval_hash,
                               receipt,last_error,captured_at,origin)
          VALUES (NEW.id,NEW.version,NEW.state,NEW.approved_at,NEW.expires_at,NEW.approval_hash,
                  NEW.receipt,NEW.last_error,strftime('%Y-%m-%dT%H:%M:%fZ','now'),'live');
      END;
      CREATE TRIGGER IF NOT EXISTS archive_case_revision AFTER UPDATE OF version ON cases
        WHEN NEW.version != OLD.version BEGIN
        INSERT INTO case_versions VALUES (NEW.id,NEW.version,NEW.payload,NEW.cv_hash,NEW.digest,
          strftime('%Y-%m-%dT%H:%M:%fZ','now'),'live');
      END;
      CREATE TRIGGER IF NOT EXISTS archive_case_event AFTER UPDATE OF
        state,version,approved_at,expires_at,approval_hash,receipt,last_error ON cases BEGIN
        INSERT INTO case_events(case_id,version,state,approved_at,expires_at,approval_hash,
                               receipt,last_error,captured_at,origin)
          VALUES (NEW.id,NEW.version,NEW.state,NEW.approved_at,NEW.expires_at,NEW.approval_hash,
                  NEW.receipt,NEW.last_error,strftime('%Y-%m-%dT%H:%M:%fZ','now'),'live');
      END;
      COMMIT;
    ''')
    for table in ('case_versions', 'case_events', 'cv_snapshots'):
        for action in ('UPDATE', 'DELETE'):
            db.execute(f'''CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action}
              BEFORE {action} ON {table} BEGIN
              SELECT RAISE(ABORT, 'archive_immutable'); END''')


def capture_cv(db, path):
    data = Path(path).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    db.execute('INSERT OR IGNORE INTO cv_snapshots VALUES (?,?,?)',
               (digest, data, datetime.now(timezone.utc).isoformat()))
    return digest


def private_write(path, data, immutable=False):
    """Pas de fichier partiel, ni d'écrasement silencieux d'une pièce figée."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if immutable and path.exists():
        if path.read_bytes() != data:
            raise ValueError('archive_content_mismatch')
        return
    tmp = path.with_name('.' + path.name + '.' + secrets.token_hex(6))
    try:
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if immutable:
            os.link(tmp, path)
        else:
            os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def json_write(path, value, immutable=False):
    private_write(path, (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode(), immutable)


def export_archives(store, destination):
    """Un instantané SQLite cohérent ; un échec d'export ne change aucun état métier."""
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    try:
        store.db.backup(db)
        count = 0
        for case in db.execute('SELECT * FROM cases'):
            folder = Path(destination) / case['created_at'][:4] / case['id']
            versions = list(db.execute('SELECT * FROM case_versions WHERE case_id=? ORDER BY version', (case['id'],)))
            missing_cv = []
            for version in versions:
                number = version['version']
                vdir = folder / 'versions' / f'v{number:04d}'
                json_write(vdir / 'dossier.json', json.loads(version['payload']), immutable=True)
                cv = db.execute('SELECT content FROM cv_snapshots WHERE sha256=?', (version['cv_hash'],)).fetchone()
                if cv:
                    if hashlib.sha256(cv[0]).hexdigest() != version['cv_hash']:
                        raise ValueError('archive_cv_corrupted')
                    private_write(vdir / 'cv.pdf', cv[0], immutable=True)
                else:
                    missing_cv.append(number)
                manifest = {k: version[k] for k in ('case_id', 'version', 'cv_hash', 'digest', 'captured_at', 'origin')}
                json_write(vdir / 'manifest.json', manifest, immutable=True)
            for event in db.execute('SELECT * FROM case_events WHERE case_id=? ORDER BY id', (case['id'],)):
                json_write(folder / 'events' / f'{event["id"]:08d}.json', dict(event), immutable=True)
            for attempt in db.execute('SELECT * FROM attempts WHERE case_id=?', (case['id'],)):
                # En cours -> terminé : seul le reçu final devient immuable.
                name = 'receipt.json' if attempt['finished_at'] else 'pending.json'
                adir = folder / 'attempts' / attempt['id']
                json_write(adir / name, dict(attempt), immutable=bool(attempt['finished_at']))
                if attempt['finished_at']:
                    (adir / 'pending.json').unlink(missing_ok=True)
            numbers = [v['version'] for v in versions]
            json_write(folder / 'index.json', {
                'case_id': case['id'], 'state': case['state'], 'version': case['version'],
                'versions_available': numbers,
                'versions_missing': sorted(set(range(1, case['version'] + 1)) - set(numbers)),
                'cv_missing_for_versions': missing_cv, 'updated_at': case['updated_at']})
            count += 1
        return count
    finally:
        db.close()
