# Organisation du projet — option A appliquée

Décision utilisateur : option A retenue le 5 novembre 2026. Deux processus distincts : [publications](publications/workflow.md) et [candidatures](candidatures/workflow.md), avec leurs archives propres.

## Classement installé

```text
README.md                       # portail des deux processus
AGENTS.md                       # règles communes et règles de chaque processus
CONTEXT.md                      # vocabulaire
memoire-linkedin.md              # référence éditoriale canonique
src/
  api/                          # client et archivage des publications
  candidatures/                 # recherche, validation, envoi et archivage
references/publications/
  positionnement/               # brief
  strategie/                    # stratégie et marque
  profil/                       # exports, travail sur le profil, bannières ; privé
  notes/                        # notes éditoriales
  ressources/                   # ressources et visuels de référence
posts/
  drafts/                       # textes et assets en préparation
  published/AAAA/MM/identifiant/ # contenu publié, métadonnées et assets
  archives/legacy/              # anciens guides, imports et copie de brouillon publié
data/
  publications/                 # études, statistiques, journal local d'envoi
  candidatures/                 # privé, hors Git
    state.sqlite3               # état courant et historique transactionnel
    candidate_facts.json
    accounts.md
    references/cv/              # original et variante du CV
    archives/AAAA/identifiant/   # versions, CV, événements et tentatives
    diagnostics/2026-11-05/      # essais historiques
output/pdf/                     # CV actif, chemin conservé
scripts/                        # lanceurs et sauvegarde
backups/                        # sauvegardes privées, hors Git
```

Les dossiers Ads/analytics vides ont été retirés. Les verrous, journaux actifs, CV de candidature, base, lanceurs, cron et configuration Chrome gardent leurs chemins d'exécution.

## Migration effectuée

- 46 fichiers déplacés ; 3 doublons strictement identiques rapprochés après comparaison des octets.
- Trois publications regroupées par année, mois et identifiant LinkedIn, avec leurs assets. Le texte Jev déjà publié est sorti des brouillons actifs ; sa copie historique reste dans `posts/archives/legacy/published-drafts/`.
- Notes éditoriales et ressource déplacées hors des brouillons. Les références de la mémoire et les liens relatifs ont été adaptés.
- L'image racine `1788427642790.jpeg`, inspectée visuellement, représente « AI does not reward speed / It rewards aim ». Elle est classée comme ressource ; aucune provenance ou publication n'a été inventée.
- Les métadonnées historiques ont été conservées. La date de brouillon Jev est postérieure à la date de publication enregistrée : cette incohérence reste signalée, sans correction arbitraire.

Le [manifeste de migration](organisation-migration-2026-11-05.json) donne les anciens et nouveaux chemins et leurs empreintes au moment du rangement. L'[audit initial](organisation-audit-2026-11-05.md) reste disponible comme document historique.

## Archivage installé

**Publications :** la commande CLI `publish` conserve le contenu, les assets et le reçu dans un journal local avant l'export. Une relance identique après succès reprend l'export, sans nouvel appel de publication. Un résultat incertain bloque le renvoi automatique. `archive` reprend uniquement les exports locaux. Les trois publications anciennes sont des imports de traces locales, pas des réponses API nouvellement obtenues.

**Candidatures :** chaque nouvelle version est conservée dans SQLite avec son contenu, ses empreintes et le PDF correspondant ; les changements d'état et décisions sont journalisés. L'export privé produit un dossier par candidature. Les deux dossiers existants ont été exportés : version 1 pour le dossier bloqué et version 3 pour Keyrus envoyé. Les versions 1 et 2 de Keyrus manquent dans l'ancien stockage et sont explicitement déclarées absentes.

Voir les contrats détaillés d'archivage : [publications](publications/archivage.md), [candidatures](candidatures/archivage.md).

## Sauvegarde et versionnement

Une sauvegarde privée préalable au rangement existe dans `backups/20261105T145814Z-before-option-a/`. La commande `python3 scripts/backup_workspace.py` produit ensuite une sauvegarde cohérente des bases SQLite via leur API, des fichiers et des configurations privées. Elle restaure chaque sauvegarde dans un dossier temporaire et vérifie les empreintes et l'intégrité SQLite.

Git sert au code et à la documentation. Les CV, exports personnels, comptes, secrets, bases, journaux et sauvegardes restent exclus. Aucun dépôt distant n'est configuré par cette migration. Aucune purge automatique n'est installée.

Les vérifications et la commande de restauration de contrôle sont décrites dans le [guide de maintenance](maintenance.md).

## Résultat des contrôles

- 66 tests réussis, dont conservation des versions/CV/décisions, migration des versions manquantes, reprise après échec d'export et absence de second envoi.
- 84 liens locaux contrôlés après rangement, aucune cible manquante.
- CV actif et deux lanceurs : empreintes identiques à la sauvegarde initiale.
- Sauvegarde `backups/20261105T151506717112Z/` restaurée temporairement et vérifiée : 156 fichiers, empreintes et intégrité SQLite conformes.
- Service Telegram relancé et actif ; deux entrées cron conservées ; aucune erreur d'archivage. États métier conservés : un dossier envoyé et un dossier bloqué.
- Exclusions Git vérifiées pour configurations, CV, exports personnels, comptes, bases et sauvegardes ; aucune occurrence des secrets locaux détectée dans les fichiers candidats au suivi.

Les essais de publication et de candidature utilisent des clients simulés. Aucun nouvel envoi distant n'a servi à valider cette migration.
