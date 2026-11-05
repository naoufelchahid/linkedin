"""Bot privé : identités vérifiées, réponses versionnées, aucune pièce jointe."""
import json
import re
from urllib.parse import urlparse
import requests
from .domain import safe_content
from .store import stamp


class TelegramError(RuntimeError):
    """Erreur volontairement sans URL : celle de l'API contient le token."""
    def __init__(self, code='telegram_unavailable', uncertain=False):
        super().__init__(code)
        self.uncertain = uncertain


class Telegram:
    def __init__(self, config, session=None):
        self.config = config
        self.session = session or requests.Session()

    def call(self, method, **payload):
        try:
            r = self.session.post(f'https://api.telegram.org/bot{self.config.token}/{method}',
                                  json=payload, timeout=(10, 40))
            data = r.json()
        except (requests.RequestException, ValueError):
            raise TelegramError(uncertain=True) from None
        if not data.get('ok'):
            code = data.get('error_code', r.status_code)
            raise TelegramError(f'telegram_http_{code}', uncertain=code >= 500)
        return data['result']

    def send(self, text, buttons=None, reply_markup=None):
        if not safe_content(text):
            raise TelegramError('excluded_content')
        payload = dict(chat_id=self.config.chat_id, text=text[:4000],
                       link_preview_options={'is_disabled': True})
        if buttons:
            payload['reply_markup'] = {'inline_keyboard': buttons}
        if reply_markup:
            payload['reply_markup'] = reply_markup
        return self.call('sendMessage', **payload)['message_id']

    def card(self, row):
        p = json.loads(row['payload'])
        contract = ('Proposition freelance ; contrat non confirmé' if p['contract'] == 'uncertain' and not p['blockers']
                    else p['contract'])
        text = (f"{p['title'][:160]} — {p['company'][:100]}\n{p['location'][:100]} · {p['work_mode'][:60]} · {contract}\n"
                f"{p['job_url']}\nDestination : {urlparse(p['apply_url']).hostname}\n\nPoste : {p['summary'][:600]}\n\n"
                f"Correspondance : {' ; '.join(p['fit_evidence'])[:400]}\n"
                f"Écarts : {' ; '.join(p['gaps'])[:250] or 'Aucun écart identifié.'}\n\n"
                f"Réponse préparée : {p['response_summary'][:600]}\n"
                f"{('À résoudre : ' + '; '.join(p['blockers'])[:300]) if p['blockers'] else ''}\n"
                f"Dossier {row['id']} · version {row['version']} · CV de référence.\n"
                'Approbation valable 24 h ; tout changement exige une nouvelle validation.')
        def button(label, action):
            return {'text': label, 'callback_data': f"{action}:{row['id']}:{row['nonce']}"}
        actions = [button('Refuser', 'reject'), button('À corriger', 'edit')]
        if not p['blockers']:
            actions.insert(0, button('Approuver', 'approve'))
        elif not p['form_complete'] and p['contract'] == 'freelance':
            actions.insert(0, button('Lire la suite', 'inspect'))
            text += ('\nLire la suite autorise la saisie des réponses connues et, si nécessaire, '
                     'le transfert du CV au formulaire de cet employeur, sans soumission finale.')
        return self.send(text, [actions, [button('Réponses exactes', 'details')]])

    def details(self, row):
        p = json.loads(row['payload'])
        parts = [f"Dossier {row['id']} — version {row['version']}"]
        parts.extend(f"{a['question']}\n{a['answer']}\nSource : {a['source']}" for a in p['answers'])
        if p['letter']:
            parts.append('Lettre :\n' + p['letter'])
        if p['blockers']:
            parts.append('À résoudre :\n' + '\n'.join(p['blockers']))
        receipt = json.loads(row['receipt']) if row.get('receipt') else {}
        if receipt.get('new_questions'):
            parts.append('Questions rencontrées sur le formulaire :\n' + '\n'.join(receipt['new_questions']))
        text = '\n\n'.join(parts)
        for start in range(0, len(text), 3800):
            self.send(text[start:start+3800])

    def poll(self, store, timeout=0):
        updates = self.call('getUpdates', offset=int(store.setting('telegram_offset', '0')),
                            timeout=timeout, limit=100, allowed_updates=['message', 'callback_query'])
        for update in sorted(updates, key=lambda u: u['update_id']):
            uid = update['update_id']
            if store.db.execute('SELECT 1 FROM updates WHERE id=?', (uid,)).fetchone():
                store.set_setting('telegram_offset', uid + 1)
                continue
            self.process(store, update)
            store.db.execute('INSERT OR IGNORE INTO updates VALUES (?)', (uid,))
            store.set_setting('telegram_offset', uid + 1)
        store.set_setting('last_poll', stamp())

    def process(self, store, update):
        cb = update.get('callback_query')
        msg = cb.get('message', {}) if cb else update.get('message', {})
        sender = cb.get('from', {}) if cb else msg.get('from', {})
        if (sender.get('id') != self.config.user_id
                or msg.get('chat', {}).get('id') != self.config.chat_id
                or msg.get('chat', {}).get('type') != 'private'):
            return
        if cb:
            match = re.fullmatch(r'(approve|reject|edit|details|inspect):([a-f0-9]{12}):([a-f0-9]{16})', cb.get('data', ''))
            if not match:
                return
            action, ident, nonce = match.groups()
            row = store.get(ident)
            if row and row['nonce'] == nonce and row['state'] == 'card_unknown' and row['message_id'] is None:
                # Un clic du propriétaire sur cette carte prouve sa livraison après un timeout.
                store.card_sent(ident, msg['message_id'])
                row = store.get(ident)
            if not row or row['message_id'] != msg.get('message_id') or row['nonce'] != nonce:
                self.call('answerCallbackQuery', callback_query_id=cb['id'], text='Carte périmée.')
                return
            if action == 'details':
                self.call('answerCallbackQuery', callback_query_id=cb['id'], text='Réponses ci-dessous.')
                self.details(row)
                return
            result = store.decide(ident, nonce, action)
            # La décision est durable même si l'accusé de réception réseau échoue.
            try:
                self.call('answerCallbackQuery', callback_query_id=cb['id'], text=result)
            except TelegramError:
                pass
            if action == 'edit' and store.get(ident)['state'] == 'needs_correction':
                message_id = self.send('Correction pour ' + ident + '. Répondez à ce message avec vos précisions.',
                                       reply_markup={'force_reply': True, 'selective': True})
                store.db.execute('UPDATE cases SET correction_message_id=? WHERE id=?', (message_id, ident))
            return
        text = msg.get('text', '')
        reply_id = msg.get('reply_to_message', {}).get('message_id')
        if reply_id:
            row = store.db.execute("SELECT id FROM cases WHERE correction_message_id=? AND state='needs_correction'",
                                   (reply_id,)).fetchone()
            if row and text and safe_content(text):
                store.db.execute("UPDATE cases SET correction=?,state='revision_queued',updated_at=? WHERE id=?",
                                 (text[:6000], stamp(), row['id']))
                self.send('Précisions reçues. Une nouvelle version sera présentée pour validation.')
            elif row:
                self.send('Cette précision est incompatible avec les consignes du dossier. Correction non enregistrée.')
            return
        if text == '/pause':
            store.set_setting('paused', 'true')
            self.send('Recherche et envois suspendus. /reprendre pour relancer.')
        elif text == '/reprendre':
            store.set_setting('paused', 'false')
            self.send('Recherche et envois réactivés selon le planning.')
        elif text == '/statut':
            counts = list(store.db.execute('SELECT state,COUNT(*) n FROM cases GROUP BY state'))
            self.send('État des candidatures :\n' + '\n'.join(f"{r['state']} : {r['n']}" for r in counts)
                      if counts else 'Aucune candidature préparée pour le moment.')
        elif text.startswith('/verifie '):
            match = re.fullmatch(r'/verifie ([a-f0-9]{12}) (envoye|non_envoye)', text)
            if not match:
                self.send('Après vérification sur le site : /verifie IDENTIFIANT envoye ou /verifie IDENTIFIANT non_envoye')
                return
            ident, outcome = match.groups()
            with store.transaction():
                row = store.get(ident)
                if not row or row['state'] != 'submission_unknown':
                    changed = False
                else:
                    changed = True
                    if outcome == 'envoye':
                        receipt = json.dumps({'verified_by_user': self.config.user_id, 'at': stamp(),
                                              'outcome': 'sent'}, ensure_ascii=False)
                        store.db.execute("UPDATE cases SET state='sent',receipt=?,updated_at=? WHERE id=?",
                                         (receipt, stamp(), ident))
                    else:
                        import secrets
                        store.db.execute('''UPDATE cases SET state='draft',nonce=?,message_id=NULL,
                          approved_at=NULL,expires_at=NULL,approval_hash=NULL,updated_at=? WHERE id=?''',
                          (secrets.token_hex(8), stamp(), ident))
            self.send(('Vérification enregistrée : envoyée.' if outcome == 'envoye'
                       else 'Vérification enregistrée : une nouvelle approbation sera demandée.')
                      if changed else 'Ce dossier ne nécessite pas de vérification d’envoi.')
        elif text.startswith('/start') or text == '/aide':
            self.send('Bot de candidatures prêt. Recherche à 21 h, heure du Maroc.\n'
                      '/statut · /pause · /reprendre\nChaque envoi nécessite votre approbation individuelle.\n'
                      'Envoi incertain : vérifiez sur le site puis /verifie IDENTIFIANT envoye ou non_envoye.')

    def dispatch(self, store):
        for row in store.rows(['draft', 'expired']):
            if not store.reserve_card(row['id']):
                continue
            try:
                message_id = self.card(store.get(row['id']))
            except TelegramError as error:
                store.transition(row['id'], 'card_unknown' if error.uncertain else 'draft', str(error))
                if not error.uncertain:
                    # Une erreur explicite n'a pas présenté un nouveau dossier.
                    if row['message_id'] is None and row['version'] == 1:
                        store.db.execute('UPDATE cases SET presented_day=NULL WHERE id=?', (row['id'],))
                    break
            else:
                store.card_sent(row['id'], message_id)
        for row in store.db.execute("SELECT * FROM notices WHERE state='pending'").fetchall():
            store.db.execute("UPDATE notices SET state='sending' WHERE key=?", (row['key'],))
            try:
                self.send(row['text'])
            except TelegramError as error:
                store.db.execute('UPDATE notices SET state=? WHERE key=?',
                                 ('unknown' if error.uncertain else 'pending', row['key']))
                break
            else:
                store.db.execute("UPDATE notices SET state='sent' WHERE key=?", (row['key'],))
