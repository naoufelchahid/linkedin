# LinkedIn — publications et candidatures

Ce projet contient **deux processus distincts** pour Naoufel Chahid / Contexte Lab. Chacun possède ses sources, sa validation et son historique. Une approbation dans un processus n'autorise aucune action dans l'autre.

| | Publication LinkedIn | Candidature à une offre |
| --- | --- | --- |
| Objectif | Préparer et publier un contenu éditorial | Trouver une mission, préparer et envoyer un dossier |
| Guide | [Parcours publication](docs/publications/workflow.md) | [Parcours candidature](docs/candidatures/workflow.md) |
| Sources de référence | [Mémoire éditoriale](memoire-linkedin.md), skill local à quatre formats | CV fixe, profil observé, précisions confirmées du candidat |
| Code actuel | `src/api/linkedin_client.py` | `src/candidatures/` |
| Validation | Validation explicite du contenu, puis `--confirm-publish` | Approbation de chaque version dans Telegram, valable 24 h |
| Exécution | API LinkedIn, déclenchement manuel | MCP LinkedIn pour la recherche ; Chrome via Playwright MCP pour les formulaires |
| Planning | Aucun planning de publication installé dans ce projet | Recherche à 21 h `Africa/Casablanca` ; réception Telegram continue |
| Historique actuel | `posts/published/AAAA/MM/identifiant/` | Base privée et `data/candidatures/archives/` |
| Règles d'archivage | [Publications](docs/publications/archivage.md) | [Candidatures](docs/candidatures/archivage.md) |

## Entrées pratiques

- **Écrire un post** : suivre le [guide publication](docs/publications/workflow.md). Les brouillons restent dans `posts/drafts/`. Le parcours éditorial fonctionne sans abonnement ni connexion LinkPost.
- **Postuler** : suivre le [guide candidature](docs/candidatures/workflow.md). Une fois le dossier approuvé dans Telegram, le worker remplit le formulaire, joint le CV et soumet sans redemander ces mêmes autorisations.
- **Exploiter le bot et Chrome** : consulter le [guide d'exploitation](docs/candidatures/exploitation.md).
- **Comprendre les deux domaines** : lire le [glossaire](CONTEXT.md) et les [instructions des agents](AGENTS.md).
- **Trouver les fichiers** : lire l'[organisation installée — option A](docs/organisation.md) et le manifeste de migration.
- **Sauvegarder ou reprendre un export** : suivre le [guide de maintenance](docs/maintenance.md).

## Configuration séparée

| Fichier local | Usage | Exemple sans secret |
| --- | --- | --- |
| `.env` | API de publication LinkedIn | [.env.example](.env.example) |
| `.env.candidatures` | Bot Telegram et activation du traitement | [.env.candidatures.example](.env.candidatures.example) |
| `.env.playwright` | Connexion à l'extension Playwright | [.env.playwright.example](.env.playwright.example) |

Les comptes employeurs nécessaires sont consignés dans `data/candidatures/accounts.md`, fichier privé exclu de Git. Ce fichier n'est ni une mémoire éditoriale ni une pièce à joindre à une candidature.

## Commandes courantes

Depuis la racine du projet :

```bash
# Diagnostic de la configuration, sans candidature
python3 -m src.candidatures doctor

# État local des dossiers
python3 -m src.candidatures list

# État de la réception continue des validations
systemctl --user status linkedin-candidatures-listener.service

# Tests locaux
python3 -m pytest -q
```

Le [guide publication](docs/publications/workflow.md) présente les commandes `auth`, `stats`, `dry-run` et `publish`. Le [guide d'exploitation des candidatures](docs/candidatures/exploitation.md) décrit les commandes qui peuvent déclencher une recherche ou un envoi approuvé.

## Périmètre réel

L'API de publication sait publier du texte ou une image et interroger des statistiques. Les modules Ads/analytics vides ont été retirés. Les études et statistiques éditoriales sont classées sous `data/publications/`.

La CLI archive les nouvelles publications confirmées. Les candidatures conservent désormais les versions, CV, décisions et tentatives, avec export privé automatique. Les versions perdues avant cette installation restent signalées comme manquantes.

Le dépôt Git local conserve le code et la documentation ; les données privées restent exclues. `python3 scripts/backup_workspace.py` sauvegarde les fichiers et les bases SQLite, puis vérifie une restauration temporaire. Aucun dépôt distant ni purge automatique n'est configuré.
