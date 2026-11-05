import copy
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
from src.candidatures.config import Config
from src.candidatures.domain import validate_candidate, file_hash, public_url
from src.candidatures.store import Store, local_day
from src.candidatures.telegram import Telegram, TelegramError
from src.candidatures.service import Service, due, lock
from src.candidatures.__main__ import cron_text


BASE = {
    'job_id': '4484363233', 'title': 'Consultant IA freelance', 'company': 'Entreprise exemple',
    'location': 'Casablanca, Maroc', 'job_url': 'https://www.linkedin.com/jobs/view/4484363233/',
    'apply_url': 'https://jobs.example.com/offre/123', 'employer_reference': '123',
    'contract': 'freelance', 'work_mode': 'hybride', 'summary': 'Conception de systèmes RAG.',
    'response_summary': 'Présentation des projets GraphRAG et intégrations ERP.',
    'fit_evidence': ['GraphRAG demandé ; GraphRAG chez Contexte Lab dans le CV.'],
    'gaps': [], 'answers': [{'question': 'Expérience pertinente ?', 'answer': 'Développement GraphRAG.',
                           'source': 'CV, Contexte Lab'}],
    'letter': '', 'blockers': [], 'form_complete': True,
}
NOW = datetime(2026, 11, 5, 21, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / 'state.sqlite3')


def add_ready(store, **changes):
    p = copy.deepcopy(BASE)
    p.update(changes)
    ident = store.add(p, 'cvhash')
    assert store.reserve_card(ident, NOW)
    store.card_sent(ident, 42)
    return store.get(ident)


def approve(store, row, now=NOW):
    return store.decide(row['id'], row['nonce'], 'approve', now)


def test_approval_required(store):
    row = add_ready(store)
    assert store.claim_submission(row['id'], 'cvhash', NOW) is None
    approve(store, row)
    assert store.claim_submission(row['id'], 'cvhash', NOW)
    assert store.claim_submission(row['id'], 'cvhash', NOW) is None


def test_listener_starts_worker_only_after_approval_and_once(store, tmp_path, monkeypatch):
    from src.candidatures import service as module
    config = Config(root=tmp_path, token='test', chat_id=1, user_id=1)
    service = Service(config, store=store)
    row = add_ready(store)
    started = []

    class Child:
        def poll(self):
            return None

    child = Child()
    def spawn(cmd, **kwargs):
        started.append(cmd)
        return child

    monkeypatch.setattr(module.subprocess, 'Popen', spawn)
    assert service.start_pending_worker() is None
    assert not started
    approve(store, row)
    assert service.start_pending_worker() is child
    assert started[0][-2:] == ['src.candidatures', 'work']
    assert service.start_pending_worker(child) is child
    assert len(started) == 1
    service.store.set_setting('paused', 'true')
    assert service.start_pending_worker() is None


def test_approval_does_not_extend_with_double_click(store):
    row = add_ready(store)
    approve(store, row)
    expiration = store.get(row['id'])['expires_at']
    approve(store, row, NOW + timedelta(hours=10))
    assert store.get(row['id'])['expires_at'] == expiration


def test_expiry_exactly_24_hours(store):
    row = add_ready(store)
    approve(store, row)
    assert store.claim_submission(row['id'], 'cvhash', NOW + timedelta(hours=24)) is None
    assert store.get(row['id'])['state'] == 'expired'


def test_cv_change_revokes_submission(store):
    row = add_ready(store)
    approve(store, row)
    assert store.claim_submission(row['id'], 'different', NOW) is None
    assert store.get(row['id'])['state'] == 'needs_correction'


def test_payload_tampering_prevents_submission(store):
    row = add_ready(store)
    approve(store, row)
    p = json.loads(row['payload'])
    p['answers'][0]['answer'] = 'Changed answer'
    store.db.execute('UPDATE cases SET payload=? WHERE id=?', (json.dumps(p), row['id']))
    assert store.claim_submission(row['id'], 'cvhash', NOW) is None


def test_rejected_cannot_be_approved(store):
    row = add_ready(store)
    store.decide(row['id'], row['nonce'], 'reject', NOW)
    approve(store, row)
    assert store.get(row['id'])['state'] == 'rejected'


@pytest.mark.parametrize('changes', [dict(contract='uncertain'), dict(form_complete=False),
                                   dict(blockers=['Disponibilité inconnue.'])])
def test_unresolved_cannot_be_approved(store, changes):
    row = add_ready(store, **changes)
    approve(store, row)
    assert store.get(row['id'])['state'] == 'blocked'


def prepare_freelance_proposal(store, **changes):
    row = add_ready(store, contract='uncertain', letter='Je propose une mission exclusivement freelance.')
    store.authorize_freelance_proposal(row['id'], 'Confirmation explicite du candidat pour cet employeur.')
    assert store.get(row['id'])['approved_at'] is None
    store.decide(row['id'], row['nonce'], 'edit', NOW)
    revised = json.loads(row['payload'])
    revised['blockers'] = []
    revised.update(changes)
    store.revise(row['id'], revised, 'cvhash')
    assert store.reserve_card(row['id'], NOW)
    store.card_sent(row['id'], 43)
    return store.get(row['id'])


def test_scoped_freelance_proposal_still_requires_new_telegram_approval(store):
    row = prepare_freelance_proposal(store)
    assert json.loads(row['payload'])['contract'] == 'uncertain'
    assert row['state'] == 'pending'
    assert store.claim_submission(row['id'], 'cvhash', NOW) is None
    approve(store, row)
    assert store.claim_submission(row['id'], 'cvhash', NOW)


@pytest.mark.parametrize('changes', [
    {'company': 'Autre employeur'}, {'apply_url': 'https://other.example.com/apply'},
    {'letter': ''}, {'blockers': ['Information obligatoire manquante.']},
])
def test_proposal_exception_cannot_change_recipient_or_clear_other_blockers(store, changes):
    row = prepare_freelance_proposal(store, **changes)
    approve(store, row)
    assert store.get(row['id'])['state'] == 'blocked'
    assert store.claim_submission(row['id'], 'cvhash', NOW) is None


def test_revoked_proposal_exception_prevents_submission(store):
    row = prepare_freelance_proposal(store)
    approve(store, row)
    store.db.execute('DELETE FROM kv WHERE key=?', ('freelance_proposal:' + row['id'],))
    assert store.claim_submission(row['id'], 'cvhash', NOW) is None


def test_revision_invalidates_old_buttons_and_approval(store):
    row = add_ready(store)
    approve(store, row)
    store.decide(row['id'], row['nonce'], 'edit', NOW)
    revised = copy.deepcopy(BASE)
    revised['answers'][0]['answer'] = 'Réponse corrigée.'
    store.revise(row['id'], revised, 'cvhash')
    new = store.get(row['id'])
    assert new['version'] == 2 and new['approval_hash'] is None
    assert new['nonce'] != row['nonce']
    assert approve(store, row) == 'Version périmée.'


def test_duplicates_across_ids_and_tracking_urls(store):
    assert store.add(copy.deepcopy(BASE), 'cvhash')
    p = copy.deepcopy(BASE)
    p.update(job_id='4484363234', job_url='https://www.linkedin.com/jobs/view/4484363234/',
             apply_url=BASE['apply_url'] + '?utm_source=linkedin')
    assert store.add(p, 'cvhash') is None


def test_daily_cap_is_twenty(store):
    reserved = []
    for i in range(22):
        p = copy.deepcopy(BASE)
        p.update(job_id=str(4484363233+i), job_url=f'https://www.linkedin.com/jobs/view/{4484363233+i}/',
                 employer_reference=str(i), apply_url=f'https://jobs.example.com/{i}')
        ident = store.add(p, 'cvhash')
        reserved.append(store.reserve_card(ident, NOW))
    assert sum(reserved) == 20


def test_unknown_or_interrupted_submission_never_retried(store):
    row = add_ready(store)
    approve(store, row)
    attempt = store.claim_submission(row['id'], 'cvhash', NOW)
    store.recover()
    assert store.get(row['id'])['state'] == 'submission_unknown'
    assert store.claim_submission(row['id'], 'cvhash', NOW) is None
    assert attempt


def test_sent_requires_observed_confirmation(store):
    row = add_ready(store)
    approve(store, row)
    attempt = store.claim_submission(row['id'], 'cvhash', NOW)
    store.finish_submission(row['id'], attempt, {'status': 'sent', 'confirmation_text': '', 'summary': ''})
    assert store.get(row['id'])['state'] == 'submission_unknown'


def test_need_input_can_be_corrected_not_reapproved(store):
    row = add_ready(store)
    approve(store, row)
    attempt = store.claim_submission(row['id'], 'cvhash', NOW)
    store.finish_submission(row['id'], attempt, {'status': 'needs_input', 'summary': 'Question supplémentaire.'})
    approve(store, row)
    assert store.get(row['id'])['state'] == 'needs_correction'
    assert store.decide(row['id'], row['nonce'], 'edit', NOW).startswith('Répondez')


@pytest.mark.parametrize('field,value', [('title', 'CDI consultant IA'), ('response_summary', 'Mon TJM est 1000'),
                                      ('summary', 'Mission 100 EUR'), ('letter', 'Salary expectations')])
def test_exclusions_are_enforced(field, value):
    p = copy.deepcopy(BASE)
    p[field] = value
    with pytest.raises(ValueError):
        validate_candidate(p)


@pytest.mark.parametrize('url', ['http://jobs.example.com', 'https://127.0.0.1/x',
                               'https://x:secret@example.com', 'https://foo.local/x'])
def test_private_or_insecure_destinations_rejected(url):
    with pytest.raises(ValueError):
        public_url(url)


class FakeTelegram(Telegram):
    def __init__(self):
        super().__init__(Config(token='unused', chat_id=10, user_id=11))
        self.calls = []

    def call(self, method, **payload):
        self.calls.append((method, payload))
        return {'message_id': 99} if method == 'sendMessage' else True


def callback(row, user=11, chat=10, message=42, action='approve'):
    return {'update_id': 1, 'callback_query': {'id': 'cb', 'from': {'id': user},
            'message': {'message_id': message, 'chat': {'id': chat, 'type': 'private'}},
            'data': f"{action}:{row['id']}:{row['nonce']}"}}


@pytest.mark.parametrize('args', [dict(user=12), dict(chat=12), dict(message=12)])
def test_unauthorized_or_wrong_message_ignored(store, args):
    row = add_ready(store)
    FakeTelegram().process(store, callback(row, **args))
    assert store.get(row['id'])['state'] == 'pending'


def test_owner_callback_approves(store):
    row = add_ready(store)
    FakeTelegram().process(store, callback(row))
    assert store.get(row['id'])['state'] == 'approved'


def test_unknown_card_delivery_can_be_reconciled_by_owner_click(store):
    row = add_ready(store)
    store.db.execute("UPDATE cases SET state='card_unknown',message_id=NULL WHERE id=?", (row['id'],))
    FakeTelegram().process(store, callback(row))
    assert store.get(row['id'])['state'] == 'approved'


def test_schedule_respects_casablanca_offset(store):
    # Déduire l'UTC de la base IANA locale, jamais d'une hypothèse UTC+1 permanente.
    local_21 = datetime(2026, 11, 5, 21, tzinfo=ZoneInfo('Africa/Casablanca'))
    utc_21 = local_21.astimezone(timezone.utc)
    assert not due(store, utc_21 - timedelta(minutes=1))
    assert due(store, utc_21)
    store.set_setting('discovery_day', '2026-11-05')
    assert not due(store, NOW)


def test_cron_install_preserves_other_projects_and_is_idempotent():
    existing = '0 2 * * * /other/project\n'
    once = cron_text(existing, Path('/home/test/project'))
    assert once.startswith(existing)
    assert once.count('# BEGIN LINKEDIN CANDIDATURES') == 1
    assert cron_text(once, Path('/home/test/project')) == once


def test_missing_config_never_starts_agent(tmp_path):
    class ExplodingAgent:
        def discover(self, seen):
            raise AssertionError('must not run')
    service = Service(Config(root=tmp_path), agent=ExplodingAgent())
    assert service.work(True) == 'configuration_required'
    assert service.poll() == 'configuration_required'


def test_exclusive_lock(tmp_path):
    path = tmp_path / 'lock'
    with lock(path) as first:
        with lock(path) as second:
            assert first and not second


def test_telegram_exception_does_not_expose_token():
    import requests
    class BrokenSession:
        def post(self, *args, **kwargs):
            raise requests.Timeout('https://api.telegram.org/botSECRET/sendMessage')
    bot = Telegram(Config(token='SECRET'), BrokenSession())
    with pytest.raises(TelegramError) as exc:
        bot.send('Test')
    assert 'SECRET' not in str(exc.value)
    assert exc.value.uncertain


def test_inspection_never_authorizes_submission(store):
    row = add_ready(store, form_complete=False)
    assert store.decide(row['id'], row['nonce'], 'inspect', NOW).startswith('Lecture')
    assert store.claim_submission(row['id'], 'cvhash', NOW) is None
    assert store.claim_submission(row['id'], 'cvhash', NOW, inspection=True)
    revised = copy.deepcopy(BASE)
    store.revise(row['id'], revised, 'cvhash')
    new = store.get(row['id'])
    assert new['state'] == 'draft' and new['approval_hash'] is None
    assert store.claim_submission(row['id'], 'cvhash', NOW) is None


def test_full_service_flow_sends_only_after_owner_approval(tmp_path):
    from src.candidatures.store import utcnow
    config = Config(root=tmp_path, token='unused', chat_id=10, user_id=11, submit_enabled=True)
    config.cv.parent.mkdir(parents=True)
    config.cv.write_bytes(b'fixed test cv')
    store = Store(config.data / 'state.sqlite3')
    class FakeAgent:
        count = 0
        def submit(self, row):
            self.count += 1
            assert row['state'] == 'submitting'
            return {'status': 'sent', 'confirmation_text': 'Application received',
                    'confirmation_url': 'https://jobs.example.com/thank-you',
                    'summary': 'Confirmation observée.', 'new_questions': []}
    agent = FakeAgent()
    telegram = FakeTelegram()
    service = Service(config, store, agent, telegram)
    store.set_setting('discovery_day', local_day())
    ident = store.add(copy.deepcopy(BASE), file_hash(config.cv))
    telegram.dispatch(store)
    row = store.get(ident)
    assert service.work() == 'idle' and agent.count == 0
    telegram.process(store, callback(row, message=row['message_id']))
    assert service.work() == 'submission_processed'
    assert store.get(ident)['state'] == 'sent'
    assert service.work() == 'idle' and agent.count == 1


def test_card_consent_is_not_truncated(store):
    row = add_ready(store, form_complete=False, summary='x'*10000,
                    response_summary='x'*10000, fit_evidence=['x'*10000], gaps=['x'*10000])
    bot = FakeTelegram()
    bot.card(row)
    sent = bot.calls[-1][1]['text']
    assert len(sent) < 4000
    assert 'sans soumission finale' in sent


def test_recovery_does_not_interfere_with_live_telegram_sender(store):
    ident = store.add(copy.deepcopy(BASE), 'cvhash')
    store.reserve_card(ident)
    store.recover()
    assert store.get(ident)['state'] == 'card_sending'
    store.recover_notifications()
    assert store.get(ident)['state'] == 'card_unknown'


@pytest.mark.parametrize('outcome,expected', [('envoye', 'sent'), ('non_envoye', 'draft')])
def test_user_can_reconcile_unknown_delivery(store, outcome, expected):
    row = add_ready(store)
    approve(store, row)
    store.claim_submission(row['id'], 'cvhash', NOW)
    store.recover()
    bot = FakeTelegram()
    bot.process(store, {'update_id': 22, 'message': {'message_id': 200, 'from': {'id': 11},
                'chat': {'id': 10, 'type': 'private'}, 'text': f"/verifie {row['id']} {outcome}"}})
    updated = store.get(row['id'])
    assert updated['state'] == expected
    if outcome == 'non_envoye':
        assert updated['approval_hash'] is None
        assert store.claim_submission(row['id'], 'cvhash', NOW) is None


def test_telegram_replay_is_deduplicated(store):
    row = add_ready(store)
    event = callback(row)
    class PollBot(FakeTelegram):
        def call(self, method, **payload):
            if method == 'getUpdates':
                return [event]
            return super().call(method, **payload)
    bot = PollBot()
    bot.poll(store)
    approved_at = store.get(row['id'])['approved_at']
    bot.poll(store)
    assert store.get(row['id'])['approved_at'] == approved_at
    assert store.db.execute('SELECT COUNT(*) FROM updates').fetchone()[0] == 1
    assert store.setting('telegram_offset') == '2'


def test_approval_expiry_does_not_change_active_submission(store):
    row = add_ready(store)
    approve(store, row)
    store.claim_submission(row['id'], 'cvhash', NOW)
    store.expire(NOW + timedelta(days=2))
    assert store.get(row['id'])['state'] == 'submitting'


def test_pause_skips_agent_work(tmp_path):
    config = Config(root=tmp_path, token='unused', chat_id=10, user_id=11)
    service = Service(config, agent=object())
    service.store.set_setting('paused', 'true')
    assert service.work(True) == 'paused'


def test_claimed_success_without_confirmation_url_is_unknown(store):
    row = add_ready(store)
    approve(store, row)
    attempt = store.claim_submission(row['id'], 'cvhash', NOW)
    store.finish_submission(row['id'], attempt, {'status': 'sent', 'confirmation_text': 'Received',
                                               'confirmation_url': '', 'summary': ''})
    assert store.get(row['id'])['state'] == 'submission_unknown'


def test_partial_search_keeps_valid_candidates(tmp_path):
    config = Config(root=tmp_path)
    config.cv.parent.mkdir(parents=True)
    config.cv.write_bytes(b'fixed test cv')
    class PartialAgent:
        def discover(self, seen):
            return {'source_status': 'partial', 'candidates': [copy.deepcopy(BASE)], 'summary': ''}
    service = Service(config, agent=PartialAgent())
    service.discover()
    assert len(service.store.rows()) == 1
    assert service.store.setting('discovery_source_status') == 'partial'
