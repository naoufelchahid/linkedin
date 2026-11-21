# Organisation actuelle du graphe 1

Le code canonique, ses dépendances, sa configuration et ses documents sont regroupés sous `jobs/graphe1/`. Le nettoyage du 20 novembre 2026 retire les expériences et les documents du second graphe du dossier `jobs/`.

| Élément | Emplacement conservé |
| --- | --- |
| Code, ressources, tests et déploiement | `jobs/graphe1/` |
| Configuration privée unique | `jobs/graphe1/.env`, permissions `600` |
| Environnement Python unique | `jobs/graphe1/.venv/` |
| Compatibilité de configuration | `jobs/.env` → `graphe1/.env` |
| Compatibilité de l’environnement | `jobs/.venv` → `graphe1/.venv` |
| Lanceur historique | `jobs/decouverte.py` |
| Anciens imports | Adaptateurs dans `src/candidatures/discovery/` |
| Base, snapshots, rapports et reçu | `data/candidatures/discovery/`, accessible par `jobs/graphe1/var` |
| CV confirmé | Chemin existant dans `.env`, conservé |
| Conception propre au graphe 1 | `jobs/graphe1/docs/conception.md` |
| Historique du test réel et de sa validation | `jobs/graphe1/docs/validation-pilote.md` |

Les anciens notebooks, le script exploratoire MCP, les vues générées et les documents du parcours de candidature futur ont été retirés du dossier de travail. Leurs contenus complets sont conservés dans la sauvegarde privée préalable `backups/20261120T151745710265Z/`, dont la restauration temporaire a été vérifiée. Le manifeste `cleanup-actions.json` y consigne les retraits ; `legacy-jobs-environment.txt` conserve les versions de l’environnement exploratoire supprimé.

Le document complet de conception avant séparation reste dans cette archive, au chemin `jobs/conception-graphe.md`. Seules ses sections consacrées au graphe 1 sont conservées dans le projet actif. Les caches générés sont supprimables et ne font pas partie de l’état métier.

La première sauvegarde de consolidation, `backups/20261120T145427992121Z/`, est également conservée. Le nettoyage ne déplace ni la base, ni le CV, ni les rapports, ni le reçu humainement validé.

## Vérification après nettoyage

Les 207 tests du dépôt passent après le nettoyage. Le lot sauvegardé est rejoué sur une copie privée : 203 annonces, 200 verdicts réutilisés et trois erreurs conservées, sans appel Apify ou Codex. Les compteurs de la base active et les empreintes du CV, du fichier de configuration et des rapports sont inchangés. Les anciens points d’entrée et la résolution des chemins relatifs sont vérifiés. Les archives de distribution excluent les fichiers privés.

## Nettoyage global de `/linkedin`

À la demande du candidat, le dépôt actif est recentré sur le graphe 1. Les publications, leur API, le moteur historique de candidature Telegram, ses données et tests, les brouillons et les références éditoriales sont retirés du dépôt. Les fichiers retirés sont conservés hors projet dans `/home/naoufel/projects/linkedin-archives/20261120T152627Z-root-cleanup/removed-from-linkedin/`. Le manifeste `root-cleanup-manifest.json` de cette archive consigne les chemins.

Le listener historique a été arrêté et désactivé, ses deux tâches cron retirées et son unité archivée. Les autres tâches cron sont conservées. Aucun nouveau service du graphe 1 n’est activé par ce nettoyage.

Les anciennes sauvegardes complètes, dont celles citées plus haut, sont déplacées sous `linkedin-archives/20261120T152627Z-root-cleanup/workspace-backups/`. La sauvegarde de contrôle immédiatement avant ce nettoyage est `20261120T152723053368Z` ; sa restauration temporaire a été vérifiée. Les sauvegardes d’état propres au graphe 1 restent sous `jobs/graphe1/backups/`.

Le code canonique, son environnement, sa configuration, le CV confirmé, l’état `data/candidatures/discovery/`, les rapports et les reçus sont conservés. Le dossier `src/candidatures/discovery/` et les trois tests de compatibilité sont également conservés pour les anciens appels. Les consignes et le glossaire à la racine décrivent désormais uniquement le graphe 1. L’historique Git est préservé.

La vérification finale du périmètre recentré passe avec 40 tests (37 tests du package et trois de compatibilité). Le rejeu du lot validé, les empreintes des fichiers actifs et les compteurs de la base sont inchangés.
