"""Journal d'envoi et archives des publications. Aucune reprise réseau implicite."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3

ROOT = Path(__file__).resolve().parents[2]
START = '<!-- linkedin:post:start -->'
END = '<!-- linkedin:post:end -->'


def read_publishable_text(path):
    text = Path(path).read_text(encoding='utf-8')
    if START in text or END in text:
        if text.count(START) != 1 or text.count(END) != 1 or text.index(START) >= text.index(END):
            raise ValueError('Délimiteurs de publication invalides.')
        text = text.split(START, 1)[1].split(END, 1)[0]
    elif text.lstrip().startswith('---'):
        raise ValueError('Métadonnées détectées : utilisez un texte seul ou les marqueurs linkedin:post:start/end.')
    if not text.strip():
        raise ValueError('Le texte publiable est vide.')
    return text.strip()


def write_file(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('publication_archive_conflict')
        return
    tmp = path.with_name('.' + path.name + '.' + secrets.token_hex(6))
    try:
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()


def journal(root):
    folder = root / 'data/publications'
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / 'state.sqlite3', timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('''CREATE TABLE IF NOT EXISTS publications (
      digest TEXT PRIMARY KEY, id TEXT NOT NULL, state TEXT NOT NULL,
      payload TEXT NOT NULL, receipt TEXT, published_at TEXT)''')
    db.commit()
    (folder / 'state.sqlite3').chmod(0o600)
    return db


def export_publication(root, row):
    payload = json.loads(row['payload'])
    receipt = json.loads(row['receipt'])
    date = row['published_at']
    folder = root / 'posts/published' / date[:4] / date[5:7] / row['id']
    text = payload['text']
    write_file(folder / 'texte-publie.txt', (text + '\n').encode())
    image_name = payload.get('image_name')
    if image_name:
        image = (root / 'data/publications/outbox' / row['id'] / image_name).read_bytes()
        if hashlib.sha256(image).hexdigest() != payload['image_sha256']:
            raise ValueError('publication_image_corrupted')
        write_file(folder / 'assets' / image_name, image)
        write_file(folder / 'assets/image.alt.txt', (payload['alt_text'] + '\n').encode())
    record = {**receipt, 'author': payload['author'], 'published_at': date,
              'content_digest': row['digest'], 'text_sha256': hashlib.sha256((text + '\n').encode()).hexdigest(),
              'image_sha256': payload.get('image_sha256'), 'source': 'api_response'}
    write_file(folder / 'publication.json', encoded(record))
    header = f'---\npublished_at: {date}\nlinkedin_post_urn: {receipt["post_urn"]}\nauthor: {payload["author"]}\n'
    if image_name:
        header += f'image: assets/{image_name}\nalt_text_file: assets/image.alt.txt\n'
    write_file(folder / 'post.md', (header + '---\n\n' + text + '\n').encode())
    return str(folder.relative_to(root))


def archive_pending(root=ROOT):
    db = journal(root)
    try:
        rows = list(db.execute("SELECT * FROM publications WHERE state='sent'"))
        return {'archives': [export_publication(root, row) for row in rows],
                'uncertain': db.execute("SELECT count(*) FROM publications WHERE state='unknown'").fetchone()[0]}
    finally:
        db.close()


def publish_archived(api, text, image=None, alt_text=None, root=ROOT):
    root = Path(root)
    # Prévalidation avant toute réservation ou transfert réseau.
    if image:
        api.create_image_post(text, image, alt_text, confirm=False)
        image_bytes = Path(image).read_bytes()
    else:
        api.create_text_post(text, confirm=False)
        image_bytes = None
    payload = {'author': api.author_urn, 'text': text.strip()}
    if image_bytes is not None:
        payload.update(image_name='image' + Path(image).suffix.lower(), alt_text=alt_text.strip(),
                       image_sha256=hashlib.sha256(image_bytes).hexdigest())
    digest = hashlib.sha256(encoded(payload)).hexdigest()
    db = journal(root)
    try:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM publications WHERE digest=?', (digest,)).fetchone()
        if row and row['state'] != 'sent':
            db.rollback()
            raise ValueError('Publication déjà tentée, résultat à vérifier. Aucun nouvel envoi automatique.')
        if row:
            db.commit()
            result = json.loads(row['receipt'])
            result['already_published'] = True
        else:
            ident = secrets.token_hex(8)
            if image_bytes is not None:
                write_file(root / 'data/publications/outbox' / ident / payload['image_name'], image_bytes)
            # Une coupure dès ce point exige une vérification, pas un renvoi.
            db.execute('INSERT INTO publications VALUES (?,?,?,?,NULL,NULL)',
                       (digest, ident, 'unknown', encoded(payload).decode()))
            db.commit()
            if image_bytes is not None:
                result = api.create_image_post(text, root / 'data/publications/outbox' / ident / payload['image_name'],
                                               alt_text, confirm=True)
            else:
                result = api.create_text_post(text, confirm=True)
            if not re.fullmatch(r'urn:li:(?:share|ugcPost):\d+', result.get('post_urn') or ''):
                raise ValueError('Réponse sans URN vérifiable : vérifier la publication avant toute reprise.')
            db.execute("UPDATE publications SET state='sent',receipt=?,published_at=? WHERE digest=?",
                       (encoded(result).decode(), datetime.now(timezone.utc).isoformat(), digest))
            db.commit()
            row = db.execute('SELECT * FROM publications WHERE digest=?', (digest,)).fetchone()
        try:
            result.update(archived=True, archive_path=export_publication(root, row))
        except (OSError, ValueError):
            # Le journal contient déjà le reçu ; archive permet une reprise purement locale.
            result.update(archived=False, archive_error='Relancer la commande archive, sans republier.')
        return result
    finally:
        db.close()
