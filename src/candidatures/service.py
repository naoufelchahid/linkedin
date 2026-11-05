"""Orchestration : le modèle prépare ; l'état local autorise les transitions."""
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import subprocess
import sys
import time
from zoneinfo import ZoneInfo
from .agent import Agent, AgentError
from .domain import file_hash, safe_content
from .store import Store, utcnow, local_day, stamp
from .telegram import Telegram
from .archive import export_archives


@contextmanager
def lock(path):
    with path.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def due(store, now=None):
    now = now or utcnow()
    local = now.astimezone(ZoneInfo('Africa/Casablanca'))
    return local.hour >= 21 and store.setting('discovery_day') != local.date().isoformat()


class Service:
    def __init__(self, config, store=None, agent=None, telegram=None):
        self.config = config
        self.store = store or Store(config.data / 'state.sqlite3')
        self.agent = agent or Agent(config)
        self.telegram = telegram or Telegram(config)
        if config.cv.exists():
            self.store.capture_cv(config.cv)

    def archive(self):
        with lock(self.config.data / 'archive.lock') as acquired:
            if not acquired:
                return 'busy'
            count = export_archives(self.store, self.config.data / 'archives')
            self.store.set_setting('archive_error', '')
            return count

    def _archive_after_action(self):
        try:
            self.archive()
        except (OSError, ValueError) as error:
            # L'état envoyé reste acquis : l'export sera repris, jamais la candidature.
            self.store.set_setting('archive_error', type(error).__name__)

    def poll(self, timeout=0):
        try:
            return self._poll(timeout)
        finally:
            self._archive_after_action()

    def _poll(self, timeout=0):
        if not self.config.ready:
            return 'configuration_required'
        with lock(self.config.data / 'telegram.lock') as acquired:
            if not acquired:
                return 'busy'
            self.store.recover_notifications()
            if timeout:
                self.telegram.poll(self.store, timeout=timeout)
            else:
                self.telegram.poll(self.store)
            self.store.expire()
            # Les approbations reçues restent valables mais aucun travail ne démarre en pause.
            if self.config.enabled and self.store.setting('paused') != 'true':
                self.telegram.dispatch(self.store)
        return 'ok'

    def start_pending_worker(self, process=None):
        """Démarrer dès la décision reçue ; le verrou du worker empêche les doublons cron."""
        if process is not None and process.poll() is None:
            return process
        if (not self.config.ready or not self.config.enabled
                or self.store.setting('paused') == 'true'
                or not self.store.rows(['approved', 'inspection_approved', 'revision_queued'])):
            return None
        with (self.config.data / 'service.log').open('a') as log:
            return subprocess.Popen([sys.executable, '-m', 'src.candidatures', 'work'],
                                    cwd=self.config.root, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=log, start_new_session=True, umask=0o077)

    def listen(self):
        """Réception Telegram continue ; la recherche quotidienne reste pilotée par cron."""
        from .config import Config
        process = None
        while True:
            try:
                config = Config.load(self.config.root)
                if config != self.config:
                    self.config, self.telegram = config, Telegram(config)
                status = self.poll(timeout=25)
                process = self.start_pending_worker(process)
                if status != 'ok':
                    time.sleep(2 if status == 'busy' else 10)
            except Exception as error:
                # Ne pas journaliser les URLs Telegram ou les identifiants.
                print('listener_error:' + type(error).__name__, flush=True)
                time.sleep(5)

    def discover(self):
        self.store.set_setting('discovery_day', local_day())
        self.store.set_setting('discovery_started', stamp())
        seen = [r['job_id'] for r in self.store.rows()]
        result = self.agent.discover(seen)
        if result['source_status'] == 'unavailable':
            self.store.notice('source:' + local_day(),
                              'Recherche indisponible. Aucun repli payant engagé ; intervention nécessaire.')
            return
        added = 0
        digest = self.store.capture_cv(self.config.cv)
        for payload in result['candidates']:
            try:
                if self.store.add(payload, digest):
                    added += 1
            except (ValueError, KeyError, TypeError):
                self.store.set_setting('last_rejected_candidate', 'invalid_or_excluded_content')
        self.store.set_setting('discovery_finished', stamp())
        self.store.set_setting('discovery_source_status', result['source_status'])
        self.store.notice('daily:' + local_day(),
                          f'Recherche terminée : {added} nouveaux dossiers pertinents préparés. '
                          'Au maximum 20 nouveaux dossiers sont présentés par jour.'
                          + (' Certaines offres n’ont pas pu être vérifiées.' if result['source_status'] == 'partial' else ''))

    def work(self, force_discovery=False):
        try:
            return self._work(force_discovery)
        finally:
            self._archive_after_action()

    def _work(self, force_discovery=False):
        if not self.config.enabled or self.store.setting('paused') == 'true':
            return 'paused'
        if not self.config.ready:
            return 'configuration_required'
        with lock(self.config.data / 'worker.lock') as acquired:
            if not acquired:
                return 'busy'
            self.store.recover()
            self.store.expire()
            if force_discovery or due(self.store):
                try:
                    self.discover()
                except AgentError as error:
                    self.store.set_setting('last_error', str(error))
                    self.store.notice('discovery-error:' + local_day(),
                                      'La recherche a échoué. Aucun dossier envoyé ; consulter le diagnostic local.')
                # Donner la main au poller et laisser les approbations guider la suite.
                return 'discovery_done'
            revisions = self.store.rows(['revision_queued'])
            if revisions:
                row = revisions[0]
                try:
                    revised = self.agent.revise(row)
                    self.store.revise(row['id'], revised, self.store.capture_cv(self.config.cv))
                except (AgentError, ValueError):
                    self.store.transition(row['id'], 'needs_correction', 'revision_failed')
                    self.store.notice('revision-error:' + row['id'] + ':' + stamp(),
                                      'Révision à reprendre pour le dossier ' + row['id'])
                return 'revision_done'
            pending = self.store.rows(['approved', 'waiting_browser', 'inspection_approved'])
            if not pending:
                return 'idle'
            if not self.config.submit_enabled:
                self.store.notice('submission-disabled',
                                  'Des candidatures sont approuvées, mais le contrôle de mise en service des envois est encore désactivé.')
                return 'submission_disabled'
            row = pending[0]
            inspection = row['state'] == 'inspection_approved'
            attempt = self.store.claim_submission(row['id'], file_hash(self.config.cv), inspection=inspection)
            if not attempt:
                return 'not_claimed'
            row = self.store.get(row['id'])
            if inspection:
                try:
                    revised = self.agent.inspect_form(row)
                    self.store.revise(row['id'], revised, self.store.capture_cv(self.config.cv))
                    self.store.db.execute('UPDATE attempts SET outcome=?,finished_at=? WHERE id=?',
                                          ('inspected_not_submitted', stamp(), attempt))
                except (AgentError, ValueError, OSError):
                    self.store.transition(row['id'], 'needs_correction', 'inspection_failed')
                    self.store.notice('inspection-error:' + attempt,
                                      'Lecture du formulaire à reprendre. Utilisez À corriger : ' + row['id'])
                return 'inspection_processed'
            try:
                result = self.agent.submit(row)
                if not safe_content(result):
                    raise AgentError('excluded_result_content')
            except (AgentError, ValueError, OSError):
                result = {'status': 'unknown', 'confirmation_text': '', 'confirmation_url': '',
                          'summary': 'Résultat incertain ; vérifier sur le site avant toute nouvelle tentative.',
                          'new_questions': []}
            self.store.finish_submission(row['id'], attempt, result)
            return 'submission_processed'

    def doctor(self, probe=False):
        report = {'telegram_configured': self.config.ready, 'cv_exists': self.config.cv.exists(),
                  'codex_found': bool(self.config.codex), 'enabled': self.config.enabled,
                  'submission_enabled': self.config.submit_enabled,
                  'time_zone': 'Africa/Casablanca', 'daily_time': '21:00',
                  'daily_limit': 20, 'approval_hours': 24,
                  'connectors_verified': self.store.setting('probe_ok') == 'true',
                  'last_connector_probe': self.store.setting('last_probe'),
                  'last_poll': self.store.setting('last_poll'),
                  'last_discovery': self.store.setting('discovery_finished')}
        report['archive_error'] = self.store.setting('archive_error', '')
        if self.config.ready:
            try:
                self.telegram.call('getMe')
                webhook = self.telegram.call('getWebhookInfo')
                report['telegram_api_ok'] = True
                report['telegram_polling_available'] = not bool(webhook.get('url'))
            except Exception:
                report['telegram_api_ok'] = False
        if probe:
            with lock(self.config.data / 'worker.lock') as acquired:
                if not acquired:
                    raise RuntimeError('worker_busy')
                result = self.agent.probe()
                report.update(result)
                self.store.set_setting('last_probe', stamp())
                self.store.set_setting('probe_ok', str(result['linkedin_ok'] and result['chrome_ok']).lower())
                report['last_connector_probe'] = self.store.setting('last_probe')
                report['connectors_verified'] = self.store.setting('probe_ok') == 'true'
        return report
