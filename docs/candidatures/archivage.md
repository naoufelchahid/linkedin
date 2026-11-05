# Archives des candidatures

Les dossiers et leurs preuves restent privés, séparés des publications. L'archivage est installé depuis le 5 novembre 2026.

## Conservation transactionnelle

- `cases` conserve l'état courant et les clés de déduplication.
- `case_versions` conserve le contenu exact, la version, les empreintes du dossier et du CV. Les révisions ne remplacent plus les anciennes versions de cette table.
- `cv_snapshots` conserve les octets du CV, indexés par SHA256. Le service prend l'instantané lors de la préparation ou révision, avant toute soumission.
- `case_events` conserve les changements d'état, décisions, portée de l'approbation, expiration et résultats. Les décisions successives d'une même version sont des événements distincts.
- `attempts` conserve chaque tentative et son reçu.

Les tables historiques sont protégées contre UPDATE et DELETE par des triggers SQLite. Cette protection empêche un écrasement accidentel par l'application ; elle n'est pas une protection contre un administrateur de la base. `candidate_facts.json` reste une référence courante ; les faits effectivement utilisés figurent dans le dossier de chaque version.

## Export privé

```text
data/candidatures/archives/AAAA/identifiant/
  index.json                   # état courant, versions disponibles et manquantes
  versions/v0001/
    dossier.json               # offre, réponses, lettre, sources
    cv.pdf                     # copie exacte quand disponible
    manifest.json              # empreintes, origine et date de capture
  events/00000001.json          # état/décision et version concernée
  attempts/identifiant/
    receipt.json               # reçu final
    pending.json               # uniquement tant que la tentative n'est pas terminée
```

Le service exporte après ses cycles de réception et de travail. Les fichiers sont écrits atomiquement ; une pièce figée déjà présente doit être identique. L'état envoyé est validé en base avant l'export : une erreur de disque ne remet jamais la candidature en file d'envoi. Le diagnostic `archive_error` signale l'erreur ; l'export est repris au cycle suivant.

Reprise manuelle, locale et sans envoi :

```bash
python3 -m src.candidatures archive
```

`index.json` et les tentatives en cours évoluent. Les versions, événements et reçus finaux restent figés. Le PDF n'est exporté que si son empreinte correspond ; une pièce introuvable est déclarée manquante.

## Reprise des dossiers existants

La migration conserve uniquement ce qui existait effectivement. Le dossier bloqué possède sa version 1 ; Keyrus envoyé possède sa version 3. Les versions 1 et 2 de Keyrus n'étaient plus présentes dans l'ancien stockage et ne sont pas reconstituées. Les captures de migration portent l'origine `migration_current_only` ; leurs dates de capture ne sont pas présentées comme les dates de création des anciennes versions.

## Confidentialité et sauvegarde

- Tout `data/candidatures/` est privé et exclu de Git. Les fichiers exportés ont des permissions `600`.
- Les comptes, tokens et fichiers `.env*` ne figurent pas dans l'export d'un dossier. `accounts.md` reste séparé.
- Les URLs de confirmation restent privées.
- L'archivage ne supprime aucun dossier de la base : la déduplication reste active pour les envois, refus, blocages et résultats incertains.
- Les diagnostics historiques sont dans `data/candidatures/diagnostics/2026-11-05/`, sans être présentés comme un historique exhaustif.
- Les sauvegardes cohérentes utilisent l'API SQLite ; ne pas copier seulement le fichier principal en activité ni déplacer ses fichiers WAL/SHM/verrous. Voir [maintenance](../maintenance.md).
- Aucune purge automatique.
