"""État durable SQLite, approbations liées à une version et reprise prudente."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
import secrets
import sqlite3
from zoneinfo import ZoneInfo
from .domain import canonical_json, fingerprint, dedupe_key, validate_candidate, canonical_apply_url, public_url
from .archive import install_history, capture_cv


def utcnow():
    return datetime.now(timezone.utc)


def stamp(now=None):
    return (now or utcnow()).isoformat()


def local_day(now=None):
    return (now or utcnow()).astimezone(ZoneInfo('Africa/Casablanca')).date().isoformat()


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          PRAGMA journal_mode=WAL;
          PRAGMA busy_timeout=30000;
          CREATE TABLE IF NOT EXISTS cases (
            id TEXT PRIMARY KEY, job_id TEXT UNIQUE NOT NULL, dedupe TEXT UNIQUE NOT NULL,
            apply_key TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL,
            cv_hash TEXT NOT NULL, digest TEXT NOT NULL, state TEXT NOT NULL,
            nonce TEXT NOT NULL, message_id INTEGER, presented_day TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            approved_at TEXT, expires_at TEXT, approval_hash TEXT,
            correction TEXT, correction_message_id INTEGER,
            receipt TEXT, last_error TEXT
          );
          CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS updates (id INTEGER PRIMARY KEY);
          CREATE TABLE IF NOT EXISTS notices (
            key TEXT PRIMARY KEY, text TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending'
          );
          CREATE TABLE IF NOT EXISTS attempts (
            id TEXT PRIMARY KEY, case_id TEXT NOT NULL, version INTEGER NOT NULL,
            started_at TEXT NOT NULL, finished_at TEXT, outcome TEXT, receipt TEXT
          );
        ''')
        install_history(self.db)
        if str(path) != ':memory:':
            from pathlib import Path
            Path(path).chmod(0o600)

    def capture_cv(self, path):
        return capture_cv(self.db, path)

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def get(self, ident):
        r = self.db.execute('SELECT * FROM cases WHERE id=?', (ident,)).fetchone()
        return dict(r) if r else None

    def rows(self, states=None):
        query = 'SELECT * FROM cases'
        params = []
        if states:
            query += ' WHERE state IN (' + ','.join('?' for _ in states) + ')'
            params = list(states)
        return [dict(r) for r in self.db.execute(query + ' ORDER BY created_at', params)]

    def setting(self, key, default=None):
        row = self.db.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key, value):
        self.db.execute('INSERT INTO kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                        (key, str(value)))

    def notice(self, key, text):
        self.db.execute('INSERT OR IGNORE INTO notices(key,text) VALUES (?,?)', (key, text))

    def authorize_freelance_proposal(self, ident, source):
        """Exception explicite pour CE destinataire ; ce n'est pas une approbation d'envoi."""
        row = self.get(ident)
        if not row or row['state'] not in ('blocked', 'needs_correction') or not source.strip():
            raise ValueError('proposal_authorization_not_allowed')
        p = json.loads(row['payload'])
        if p['contract'] != 'uncertain':
            raise ValueError('proposal_authorization_not_needed')
        self.set_setting('freelance_proposal:' + ident, canonical_json({
            'job_id': p['job_id'], 'company': p['company'],
            'apply_url': canonical_apply_url(p['apply_url']),
            'source': source, 'confirmed_at': stamp()}))

    def freelance_proposal_allowed(self, ident, payload):
        raw = self.setting('freelance_proposal:' + ident)
        if not raw or payload['contract'] != 'uncertain':
            return False
        scope = json.loads(raw)
        return (scope.get('job_id') == payload['job_id']
                and scope.get('company') == payload['company']
                and scope.get('apply_url') == canonical_apply_url(payload['apply_url'])
                and bool(scope.get('source'))
                and 'freelance' in payload.get('letter', '').casefold())

    def add(self, payload, cv_hash):
        p = validate_candidate(payload)
        ident = secrets.token_hex(6)
        apply_key = canonical_apply_url(p['apply_url'])
        # Une destination identique ne distingue pas deux publications du même poste.
        if self.db.execute('SELECT 1 FROM cases WHERE apply_key=?', (apply_key,)).fetchone():
            return None
        try:
            self.db.execute('''INSERT INTO cases
              (id,job_id,dedupe,apply_key,version,payload,cv_hash,digest,state,nonce,created_at,updated_at)
              VALUES (?,?,?,?,1,?,?,?,?,?,?,?)''',
              (ident, p['job_id'], dedupe_key(p), apply_key, canonical_json(p), cv_hash,
               fingerprint(p, cv_hash), 'draft', secrets.token_hex(8), stamp(), stamp()))
        except sqlite3.IntegrityError:
            return None
        return ident

    def reserve_card(self, ident, now=None):
        """Compter avant l'appel réseau : un envoi incertain ne permet pas de dépasser 20."""
        with self.transaction():
            row = self.get(ident)
            if not row or row['state'] not in ('draft', 'expired'):
                return False
            day = local_day(now)
            if not row['presented_day']:
                used = self.db.execute('SELECT COUNT(*) FROM cases WHERE presented_day=?', (day,)).fetchone()[0]
                if used >= 20:
                    return False
            self.db.execute('''UPDATE cases SET state='card_sending',
              presented_day=COALESCE(presented_day,?), updated_at=? WHERE id=?''', (day, stamp(now), ident))
            return True

    def card_sent(self, ident, message_id):
        row = self.get(ident)
        p = json.loads(row['payload'])
        state = 'blocked' if p['blockers'] else 'pending'
        self.db.execute('UPDATE cases SET state=?,message_id=?,updated_at=? WHERE id=?',
                        (state, message_id, stamp(), ident))

    def transition(self, ident, state, error=None):
        self.db.execute('UPDATE cases SET state=?,last_error=?,updated_at=? WHERE id=?',
                        (state, error, stamp(), ident))

    def decide(self, ident, nonce, action, now=None):
        now = now or utcnow()
        with self.transaction():
            r = self.get(ident)
            if not r or not secrets.compare_digest(r['nonce'], nonce):
                return 'Version périmée.'
            if r['state'] not in ('pending', 'blocked', 'approved', 'waiting_browser', 'expired',
                                  'needs_correction', 'inspection_approved'):
                return 'Cette décision a déjà été traitée.'
            if action in ('approve', 'inspect'):
                if r['state'] == 'needs_correction':
                    return 'Une correction et une nouvelle version sont nécessaires.'
                p = json.loads(r['payload'])
                contract_ok = p['contract'] == 'freelance' or self.freelance_proposal_allowed(ident, p)
                if action == 'approve' and (p['blockers'] or not p['form_complete'] or not contract_ok):
                    return 'Des points restent à résoudre : utilisez À corriger.'
                if action == 'inspect' and (p['form_complete'] or p['contract'] != 'freelance'):
                    return 'Inspection non nécessaire ou contrat encore incertain.'
                if r['state'] in ('approved', 'waiting_browser', 'inspection_approved'):
                    return 'Déjà approuvée ; le délai initial reste inchangé.'
                self.db.execute('''UPDATE cases SET state=?,approved_at=?,expires_at=?,
                  approval_hash=digest,updated_at=? WHERE id=?''',
                  ('approved' if action == 'approve' else 'inspection_approved',
                   stamp(now), stamp(now + timedelta(hours=24)), stamp(now), ident))
                return 'Approuvée pour 24 heures.' if action == 'approve' else 'Lecture autorisée, sans soumission finale.'
            if action in ('reject', 'edit'):
                state = 'rejected' if action == 'reject' else 'needs_correction'
                self.db.execute('''UPDATE cases SET state=?,approved_at=NULL,expires_at=NULL,
                  approval_hash=NULL,updated_at=? WHERE id=?''', (state, stamp(now), ident))
                return 'Refusée.' if action == 'reject' else 'Répondez au message de correction.'
            return 'Action inconnue.'

    def revise(self, ident, payload, cv_hash):
        p = validate_candidate(payload, allow_freelance_proposal=self.freelance_proposal_allowed(ident, payload))
        with self.transaction():
            row = self.get(ident)
            if row['state'] not in ('revision_queued', 'needs_correction', 'inspecting') or p['job_id'] != row['job_id']:
                raise ValueError('revision_not_allowed')
            self.db.execute('''UPDATE cases SET version=version+1,payload=?,cv_hash=?,digest=?,
              apply_key=?,dedupe=?,
              state='draft',nonce=?,message_id=NULL,approved_at=NULL,expires_at=NULL,
              approval_hash=NULL,correction_message_id=NULL,receipt=NULL,updated_at=? WHERE id=?''',
              (canonical_json(p), cv_hash, fingerprint(p, cv_hash), canonical_apply_url(p['apply_url']),
               dedupe_key(p), secrets.token_hex(8), stamp(), ident))

    def expire(self, now=None):
        now = now or utcnow()
        for r in self.rows(['approved', 'waiting_browser', 'inspection_approved']):
            if datetime.fromisoformat(r['expires_at']) <= now:
                self.db.execute('''UPDATE cases SET state='expired',nonce=?,approval_hash=NULL,updated_at=?
                  WHERE id=? AND state IN ('approved','waiting_browser','inspection_approved')''',
                  (secrets.token_hex(8), stamp(now), r['id']))

    def claim_submission(self, ident, cv_hash, now=None, inspection=False):
        now = now or utcnow()
        with self.transaction():
            r = self.get(ident)
            eligible = ('inspection_approved',) if inspection else ('approved', 'waiting_browser')
            if not r or r['state'] not in eligible:
                return None
            payload = json.loads(r['payload'])
            if payload['contract'] != 'freelance' and not self.freelance_proposal_allowed(ident, payload):
                self.transition(ident, 'needs_correction', 'contract_not_authorized')
                return None
            if datetime.fromisoformat(r['expires_at']) <= now:
                self.transition(ident, 'expired')
                return None
            if r['cv_hash'] != cv_hash or r['approval_hash'] != fingerprint(json.loads(r['payload']), cv_hash):
                self.transition(ident, 'needs_correction', 'document_changed')
                self.notice('cv:' + ident + ':' + str(r['version']),
                            'Le CV ou le dossier a changé. Nouvelle préparation et validation nécessaires : ' + ident)
                return None
            attempt = secrets.token_hex(8)
            self.db.execute('INSERT INTO attempts(id,case_id,version,started_at) VALUES (?,?,?,?)',
                            (attempt, ident, r['version'], stamp(now)))
            self.transition(ident, 'inspecting' if inspection else 'submitting')
            return attempt

    def finish_submission(self, ident, attempt, result):
        statuses = {'sent': 'sent', 'closed': 'closed', 'browser_unavailable': 'waiting_browser',
                    'needs_input': 'needs_correction', 'unknown': 'submission_unknown'}
        state = statuses.get(result['status'], 'submission_unknown')
        # Un simple résultat positif du modèle ne suffit pas sans texte de confirmation.
        if state == 'sent' and not result.get('confirmation_text'):
            state = 'submission_unknown'
        if state == 'sent':
            try:
                public_url(result.get('confirmation_url', ''))
            except ValueError:
                state = 'submission_unknown'
        receipt = canonical_json(result)
        with self.transaction():
            self.db.execute('UPDATE attempts SET finished_at=?,outcome=?,receipt=? WHERE id=?',
                            (stamp(), state, receipt, attempt))
            self.db.execute('UPDATE cases SET state=?,receipt=?,updated_at=? WHERE id=?',
                            (state, receipt, stamp(), ident))
            if state == 'needs_correction':
                self.db.execute('UPDATE cases SET approval_hash=NULL WHERE id=?', (ident,))
            labels = {'sent': 'envoyée', 'closed': 'offre fermée', 'waiting_browser': 'en attente de Chrome',
                      'needs_correction': 'précision nécessaire', 'submission_unknown': 'envoi à vérifier'}
            text = f'Candidature {ident} : {labels[state]}. ' + result.get('summary', '')
            if state == 'needs_correction':
                text += '\n' + '\n'.join(result.get('new_questions', []))
                text += '\nUtilisez À corriger sur la carte du dossier.'
            self.notice('outcome:' + attempt, text)

    def recover(self):
        # Appelé uniquement avec le verrou exclusif du worker acquis.
        for r in self.rows(['submitting']):
            self.transition(r['id'], 'submission_unknown', 'interrupted')
            self.notice('interrupted:' + r['id'],
                        'Envoi interrompu, vérification manuelle nécessaire avant toute reprise : ' + r['id'])
        for r in self.rows(['inspecting']):
            self.transition(r['id'], 'needs_correction', 'inspection_interrupted')
            self.notice('inspection-interrupted:' + r['id'],
                        'Lecture de formulaire interrompue. Utilisez À corriger pour reprendre le dossier ' + r['id'])

    def recover_notifications(self):
        # Seulement sous verrou Telegram : ne pas interrompre un envoi réseau actif.
        for r in self.rows(['card_sending']):
            self.transition(r['id'], 'card_unknown', 'interrupted')
        self.db.execute("UPDATE notices SET state='unknown' WHERE state='sending'")
