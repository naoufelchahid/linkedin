import copy
import json
import sqlite3
from unittest.mock import Mock
import pytest
import requests
from src.candidatures.store import Store
from src.candidatures.archive import export_archives
from src.candidatures.config import Config
from src.candidatures.service import Service
from src.api.linkedin_client import LinkedInAPI, LinkedInAPIError
from src.api import publication_archive as pub
from test_candidatures import BASE, NOW, add_ready, approve


def test_revisions_keep_exact_answers_cv_and_decisions(tmp_path):
    store = Store(tmp_path / 'state.sqlite3')
    cv = tmp_path / 'cv.pdf'
    cv.write_bytes(b'first cv')
    digest = store.capture_cv(cv)
    ident = store.add(copy.deepcopy(BASE), digest)
    store.reserve_card(ident, NOW)
    store.card_sent(ident, 42)
    row = store.get(ident)
    approve(store, row)
    store.decide(ident, row['nonce'], 'edit', NOW)
    revised = copy.deepcopy(BASE)
    revised['answers'][0]['answer'] = 'Nouvelle réponse confirmée.'
    cv.write_bytes(b'second cv')
    store.revise(ident, revised, store.capture_cv(cv))
    export_archives(store, tmp_path / 'archives')
    folder = next((tmp_path / 'archives').glob('*/*'))
    first = folder / 'versions/v0001'
    second = folder / 'versions/v0002'
    assert json.loads((first / 'dossier.json').read_text())['answers'] == BASE['answers']
    assert (first / 'cv.pdf').read_bytes() == b'first cv'
    assert (second / 'cv.pdf').read_bytes() == b'second cv'
    events = [json.loads(p.read_text()) for p in (folder / 'events').glob('*.json')]
    assert any(e['state'] == 'approved' and e['version'] == 1 and e['approval_hash'] == row['digest'] for e in events)
    assert store.get(ident)['approval_hash'] is None
    with pytest.raises(sqlite3.IntegrityError, match='archive_immutable'):
        store.db.execute('DELETE FROM case_versions')
    (first / 'dossier.json').write_text('corrupted')
    with pytest.raises(ValueError, match='archive_content_mismatch'):
        export_archives(store, tmp_path / 'archives')


def test_migration_does_not_invent_missing_versions(tmp_path):
    path = tmp_path / 'state.sqlite3'
    store = Store(path)
    ident = store.add(copy.deepcopy(BASE), 'missing-cv')
    for name, in store.db.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
        store.db.execute(f'DROP TRIGGER {name}')
    for table in ('case_versions', 'case_events', 'cv_snapshots'):
        store.db.execute(f'DROP TABLE {table}')
    store.db.execute('UPDATE cases SET version=3 WHERE id=?', (ident,))
    store.db.close()
    store = Store(path)
    export_archives(store, tmp_path / 'archives')
    index = json.loads(next((tmp_path / 'archives').glob('*/*/index.json')).read_text())
    assert index['versions_available'] == [3]
    assert index['versions_missing'] == [1, 2]
    assert index['cv_missing_for_versions'] == [3]


def test_failed_candidate_export_cannot_requeue_sent_case(tmp_path, monkeypatch):
    from src.candidatures import service as module
    store = Store(tmp_path / 'state.sqlite3')
    row = add_ready(store)
    approve(store, row)
    attempt = store.claim_submission(row['id'], 'cvhash', NOW)
    store.finish_submission(row['id'], attempt, {'status': 'sent', 'confirmation_text': 'Merci',
                                                'confirmation_url': 'https://jobs.example.com/received'})
    service = Service(Config(root=tmp_path), store=store)
    monkeypatch.setattr(module, 'export_archives', Mock(side_effect=OSError('full disk')))
    service._archive_after_action()
    assert store.get(row['id'])['state'] == 'sent'
    assert store.claim_submission(row['id'], 'cvhash', NOW) is None
    assert store.setting('archive_error') == 'OSError'


def api_with_response():
    session = Mock()
    response = Mock(status_code=201, ok=True)
    response.headers = {'x-restli-id': 'urn:li:share:123'}
    session.request.return_value = response
    return LinkedInAPI(access_token='fake', author_urn='urn:li:person:test', session=session)


def test_publication_export_retry_does_not_publish_twice(tmp_path, monkeypatch):
    api = api_with_response()
    original = pub.export_publication
    monkeypatch.setattr(pub, 'export_publication', Mock(side_effect=OSError('disk full')))
    result = pub.publish_archived(api, 'Texte validé', root=tmp_path)
    assert result['post_urn'] and not result['archived']
    monkeypatch.setattr(pub, 'export_publication', original)
    result = pub.publish_archived(api, 'Texte validé', root=tmp_path)
    assert result['already_published'] and result['archived']
    assert api.session.request.call_count == 1
    assert (tmp_path / result['archive_path'] / 'texte-publie.txt').read_text() == 'Texte validé\n'


def test_ambiguous_publication_is_not_retried(tmp_path):
    api = api_with_response()
    api.session.request.side_effect = requests.Timeout('timeout')
    with pytest.raises(LinkedInAPIError):
        pub.publish_archived(api, 'Texte validé', root=tmp_path)
    with pytest.raises(ValueError, match='déjà tentée'):
        pub.publish_archived(api, 'Texte validé', root=tmp_path)
    assert api.session.request.call_count == 1


def test_extract_only_explicit_approved_block(tmp_path):
    path = tmp_path / 'post.md'
    path.write_text('---\nnotes: internes\n---\nTexte')
    with pytest.raises(ValueError, match='Métadonnées'):
        pub.read_publishable_text(path)
    path.write_text('Notes privées\n' + pub.START + '\nTexte validé\n' + pub.END + '\nSources privées')
    assert pub.read_publishable_text(path) == 'Texte validé'


def test_cv_buffer_source_serves_only_matching_authorized_file(tmp_path):
    import hashlib
    import requests
    from src.candidatures.upload import cv_buffer_source
    path = tmp_path / 'cv.pdf'
    path.write_bytes(b'authorized pdf bytes')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with cv_buffer_source(path, digest) as url:
        response = requests.get(url, timeout=2)
        assert response.content == path.read_bytes()
        assert response.headers['Cache-Control'] == 'no-store'
        assert requests.get(url + '/other', timeout=2).status_code == 404
    with pytest.raises(ValueError, match='cv_changed_before_upload'):
        with cv_buffer_source(path, 'different'):
            pass
