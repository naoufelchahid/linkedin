#!/bin/sh
# Environnement explicite pour cron ; aucune clé API dans le script ou les arguments.
set -eu
umask 077
PROJECT_DIR='/home/naoufel/projects/linkedin'
export PATH='/home/naoufel/.nvm/versions/node/v24.14.0/bin:/home/naoufel/.local/bin:/usr/local/bin:/usr/bin:/bin'
export LANG=C.UTF-8
cd "$PROJECT_DIR"
mkdir -p data/candidatures
chmod 700 data/candidatures
# Logs de statut uniquement ; le modèle et les requêtes API n'y écrivent pas leur contenu.
exec /usr/bin/python3 -m src.candidatures "$@" >> data/candidatures/service.log 2>&1
