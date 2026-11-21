# Graphe 1 — découverte et qualification

Application autonome du premier graphe validé : découverte avec Apify, qualification des **missions uniquement** par Codex App Server, état SQLite et rapport HTML privé. Le package ne prépare ni n’envoie de candidature.

## Organisation

```text
graphe1/
├── pyproject.toml              # Package, commande et outils de développement
├── uv.lock                    # Verrou complet, développement compris
├── requirements.lock          # Export de production avec empreintes
├── .env.example               # Configuration sans secret
├── src/linkedin_discovery/
│   ├── cli.py                 # Commandes et codes de sortie
│   ├── config.py              # Chemins et configuration explicites
│   ├── graph.py               # Définition LangGraph
│   ├── workflow.py            # Collecte, qualification, revue et reprise
│   ├── model.py               # Identité, classement et preuves
│   ├── store.py               # SQLite, versions, tentatives et verrou
│   ├── report.py              # Échantillon et rapports immuables
│   ├── maintenance.py         # Sauvegarde et contrôle de restauration
│   ├── adapters/              # Apify, Codex App Server et PDF
│   └── resources/             # Prompt validé et schéma SQL embarqués
├── tests/                     # Tests métier et d’exploitation, sans réseau
├── deploy/                    # Unités systemd préparées
└── docs/                      # Exploitation et réorganisation
```

Le runtime fonctionne depuis une wheel installée, sans checkout ni document Markdown de conception. Le prompt embarqué correspond exactement à celui du lot validé. Une modification de prompt est explicite et entraîne une nouvelle version de qualification.

## Installation

Prérequis : Linux, Python 3.12 ou 3.13, `pdftotext` (paquet système `poppler-utils`), Codex CLI authentifié avec l’accès existant. Le raccord a été vérifié avec Codex 0.171.0.

Depuis ce dossier :

```bash
uv sync --locked
uv run --locked linkedin-discovery doctor
uv run --locked linkedin-discovery status
```

Installation dédiée à l’exécution :

```bash
uv sync --locked --no-dev
.venv/bin/linkedin-discovery --home /chemin/absolu/graphe1 doctor
```

`--home` désigne le dossier de configuration et d’état, indépendamment de l’installation du package. Sans cet argument, `DISCOVERY_HOME` puis le répertoire courant sont utilisés.

Sur une nouvelle installation, créer `.env` depuis `.env.example`, avec permissions `600`. Renseigner `APIFY_TOKEN` et `DISCOVERY_CV` avec le chemin du CV confirmé. `DISCOVERY_DATA_DIR` désigne un état persistant externe ; par défaut, il va sous `var/`. Les chemins relatifs sont résolus par rapport au home. `--env-file` désigne un autre fichier privé. Les variables d’environnement ont priorité sur le fichier.

Dans ce workspace, la configuration privée est dans `graphe1/.env`. Les anciens chemins `jobs/.env` et `jobs/.venv` sont des liens vers la configuration et l’environnement uniques du projet. `graphe1/var` pointe vers `data/candidatures/discovery/` : la base, les snapshots de CV, les rapports et les reçus conservent leurs emplacements. Les liens locaux et secrets restent hors Git et hors distribution ; voir le [plan de réorganisation](docs/reorganisation.md).

## Exécution

```bash
.venv/bin/linkedin-discovery discover
.venv/bin/linkedin-discovery discover --daily --fail-on-errors
.venv/bin/linkedin-discovery status
.venv/bin/linkedin-discovery resume ID_CYCLE --fail-on-errors
.venv/bin/linkedin-discovery report ID_CYCLE
```

`discover` crée un cycle manuel. `--daily` retrouve le cycle planifié du jour en `Africa/Casablanca` : une relance reprend ses runs au lieu d’en lancer de nouveaux. Un verrou protège la création et l’exécution.

Chaque recherche demande au plus 100 résultats au Maroc sur sept jours. L’attente de collecte est bornée ; un bilan partiel conserve les résultats disponibles. Les appels HTTP ont leurs propres délais ; les lectures transitoires sont retentées au plus trois fois. Un POST de lancement Apify n’est jamais répété automatiquement après une issue incertaine.

Codex reçoit une annonce à la fois, sans outils ni MCP. Les sorties structurées et les citations sont vérifiées. Les missions imprécises sont retenues avec incertitude ; les prérequis ne participent pas au verdict. Les qualifications réutilisent les versions identiques d’annonce, de CV et de prompt. Le budget est d’au plus trois tentatives par qualification, interruptions comprises.

Le classement garde Casablanca/Rabat en premier, puis le remote ou télétravail explicitement observé, puis les autres lieux. Les dates les plus récentes passent d’abord dans chaque groupe. La revue vise cinq retenues sans incertitude, cinq avec incertitude et cinq écartées selon disponibilité.

## Revue et sauvegarde

```bash
.venv/bin/linkedin-discovery review --report ID_RAPPORT --number 1 --verdict retenir
.venv/bin/linkedin-discovery replay --report ID_RAPPORT
.venv/bin/linkedin-discovery compare --report ID_RAPPORT --cycle ID_CYCLE_REJEU
.venv/bin/linkedin-discovery backup
.venv/bin/linkedin-discovery verify-backup backups/discovery-DATE.tar.gz
```

Enregistrer seulement les verdicts effectivement reçus du candidat. La correction humaine est liée à la version examinée et reste séparée du verdict Codex. Les rapports sont figés et versionnés. `replay` reprend les mêmes annonces et le CV sauvegardé avec le prompt embarqué, ou celui fourni par `--prompt-file`.

La sauvegarde inclut la base via l’API SQLite, les snapshots de CV, les rapports et les reçus. Une restauration de contrôle vérifie les empreintes et l’intégrité SQLite. Les secrets de configuration sont sauvegardés séparément. Voir le [guide d’exploitation](docs/exploitation.md).

## Vérification et distribution

```bash
uv sync --locked
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
uv run --locked pytest -q
uv build
```

Les archives sous `dist/` contiennent le package et ses ressources, sans `.env`, CV, base ni rapport utilisateur. Les unités de `deploy/` décrivent l’installation locale à 21 h Casablanca. Elles sont préparées pour une activation ultérieure ; l’installation du package ne remplace ni n’active aucun service existant.

Pour installer la wheel avec `pip` dans un environnement dédié :

```bash
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps dist/linkedin_discovery-1.0.0-py3-none-any.whl
```

Le [bilan de vérification](docs/verification.md) conserve les tests, l’installation isolée et le contrôle de reprise du lot validé.

Pour voir le graphe dans Studio, installer le groupe `studio` puis lancer `uv run --locked --group studio langgraph dev` depuis ce dossier. Le [guide d’exploitation](docs/exploitation.md#studio-local) décrit le démarrage et l’entrée `cycle_id`. Les traces détaillées, activables avec `DISCOVERY_TRACE_CONTENT=true`, montrent l’annonce, le CV, le prompt et les résultats dans LangSmith.

La [conception du graphe 1](docs/conception.md), la [décision d’architecture](docs/architecture.md) et le [bilan du pilote validé](docs/validation-pilote.md) sont regroupés avec le projet.
