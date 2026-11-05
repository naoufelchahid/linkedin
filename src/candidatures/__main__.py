"""Commandes d'installation et d'exploitation du système local."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
from .config import Config, ROOT
from .service import Service, lock
from .telegram import Telegram, TelegramError
from .agent import AgentError
from .store import Store


def save_config(config):
    path = config.root / '.env.candidatures'
    text = (f'TELEGRAM_BOT_TOKEN={config.token}\nTELEGRAM_CHAT_ID={config.chat_id}\n'
            f'TELEGRAM_USER_ID={config.user_id}\nCANDIDATURES_ENABLED={str(config.enabled).lower()}\n'
            f'CANDIDATURES_SUBMIT_ENABLED={str(config.submit_enabled).lower()}\n')
    tmp = path.with_suffix('.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(text)
    os.replace(tmp, path)
    path.chmod(0o600)


def configure(config):
    print('Créez un bot dédié via https://t.me/BotFather avec /newbot.')
    token = getpass.getpass('Token Telegram (saisie masquée, stocké localement) : ').strip()
    if not re.fullmatch(r'\d+:[A-Za-z0-9_-]{20,}', token):
        raise ValueError('Format du token invalide.')
    config.token = token
    bot = Telegram(config)
    info = bot.call('getMe')
    if bot.call('getWebhookInfo').get('url'):
        raise ValueError('Ce bot utilise déjà un webhook. Utilisez un bot dédié sans webhook.')
    nonce = secrets.token_hex(12)
    print(f"Ouvrez https://t.me/{info['username']}?start={nonce} dans votre compte Telegram et appuyez sur Démarrer.")
    input('Une fois le message envoyé, appuyez sur Entrée ici : ')
    updates = bot.call('getUpdates', timeout=0, allowed_updates=['message', 'callback_query'])
    matching = [u for u in updates if u.get('message', {}).get('text') == '/start ' + nonce
                and u['message'].get('chat', {}).get('type') == 'private'
                and not u['message'].get('from', {}).get('is_bot', True)]
    if len(matching) != 1:
        raise ValueError('Message de liaison unique non trouvé. Relancez configure.')
    message = matching[0]['message']
    config.chat_id = message['chat']['id']
    config.user_id = message['from']['id']
    save_config(config)
    store = Store(config.data / 'state.sqlite3')
    # Le bot est dédié ; les événements antérieurs à la liaison ne sont pas des décisions.
    store.set_setting('telegram_offset', max(u['update_id'] for u in updates) + 1)
    bot.send('Bot relié à votre compte. Recherche quotidienne à 21 h, heure du Maroc. '
             'Chaque candidature demandera votre validation. /statut · /pause · /reprendre')
    print('Bot configuré ; token enregistré en .env.candidatures (permissions 600).')


def cron_text(existing, root):
    start, end = '# BEGIN LINKEDIN CANDIDATURES', '# END LINKEDIN CANDIDATURES'
    block = re.compile(r'(?ms)^' + re.escape(start) + r'\n.*?^' + re.escape(end) + r'\n?')
    base = block.sub('', existing).rstrip()
    launcher = shlex.quote(str(root / 'scripts/candidatures.sh'))
    # Cron tourne en UTC sur cet hôte. Le worker vérifie ZoneInfo à chaque réveil.
    lines = [start, '# Le programme applique 21:00 Africa/Casablanca ; aucune modification du fuseau système.',
             f'*/5 * * * * {launcher} poll', f'*/5 * * * * {launcher} work', end]
    return (base + '\n' if base else '') + '\n'.join(lines) + '\n'


def install_cron(config):
    previous = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    if previous.returncode not in (0, 1):
        raise RuntimeError('Lecture du crontab impossible.')
    if previous.returncode == 1 and previous.stdout:
        raise RuntimeError('État du crontab ambigu.')
    old = previous.stdout
    backup = config.data / 'crontab.before.txt'
    if not backup.exists():
        backup.write_text(old)
        backup.chmod(0o600)
    updated = cron_text(old, config.root)
    # Éviter d'écraser un changement concurrent d'un autre projet.
    reread = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    if reread.stdout != old:
        raise RuntimeError('Le crontab a changé ; réessayez.')
    subprocess.run(['crontab', '-'], input=updated, text=True, check=True)
    check = subprocess.run(['crontab', '-l'], capture_output=True, text=True, check=True)
    if check.stdout != updated:
        raise RuntimeError('Vérification du crontab échouée.')
    print('Cron installé et vérifié. Recherche à 21 h Africa/Casablanca ; réveil toutes les 5 minutes.')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description='Candidatures freelance LinkedIn et validation Telegram')
    parser.add_argument('command', choices=['configure', 'doctor', 'install-cron', 'poll', 'work',
                                          'discover', 'list', 'pause', 'resume', 'enable-submission', 'listen', 'archive'])
    parser.add_argument('--probe', action='store_true', help='Tester les connecteurs en lecture seule')
    args = parser.parse_args()
    config = Config.load()
    if args.command == 'configure':
        configure(config)
        return
    if args.command == 'install-cron':
        install_cron(config)
        return
    service = Service(config)
    if args.command == 'doctor':
        print(json.dumps(service.doctor(args.probe), ensure_ascii=False, indent=2))
    elif args.command in ('work', 'discover'):
        print(service.work(force_discovery=args.command == 'discover'))
    elif args.command == 'poll':
        print(service.poll())
    elif args.command == 'listen':
        service.listen()
    elif args.command == 'archive':
        print(json.dumps({'archives_exported': service.archive()}))
    elif args.command == 'list':
        print(json.dumps([{k: r[k] for k in ('id', 'job_id', 'version', 'state', 'expires_at')}
                          for r in service.store.rows()], indent=2))
    elif args.command in ('pause', 'resume'):
        service.store.set_setting('paused', 'true' if args.command == 'pause' else 'false')
        print(args.command)
    elif args.command == 'enable-submission':
        if service.store.setting('probe_ok') != 'true':
            raise ValueError('Lancez doctor --probe avec succès avant activation.')
        config.submit_enabled = True
        save_config(config)
        print('Envoi activé ; chaque dossier exige toujours son approbation Telegram individuelle.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, TelegramError, AgentError, OSError, subprocess.SubprocessError) as error:
        # Ne jamais afficher un traceback requests contenant le token dans son URL.
        print('Erreur : ' + (str(error) if isinstance(error, (ValueError, RuntimeError))
                            else type(error).__name__), file=sys.stderr)
        sys.exit(1)
