# Maintenance des deux processus

## Vérifications locales

```bash
python3 -m pytest -q
python3 -m src.candidatures archive
python3 src/api/linkedin_client.py archive
systemctl --user status linkedin-candidatures-listener.service
```

Les deux commandes `archive` n'effectuent ni publication, ni recherche d'offres, ni soumission. Elles reprennent les exports locaux. Les tests utilisent des données fictives et des clients réseau simulés.

## Sauvegarde et restauration de contrôle

```bash
python3 scripts/backup_workspace.py
python3 scripts/backup_workspace.py --verify backups/IDENTIFIANT
```

La sauvegarde contient le code, les documents, les CV, les comptes, les configurations privées et une copie cohérente de chaque base SQLite. Elle est privée (`backups/`, répertoire `700`, fichiers `600`), exclue de Git et doit rester sur un support de confiance. Les caches, `tmp/`, Git, verrous et fichiers WAL/SHM sont exclus ; les transactions validées sont incorporées aux instantanés SQLite.

Chaque sauvegarde est automatiquement restaurée dans un dossier temporaire : empreintes SHA256 et `PRAGMA integrity_check` sont vérifiés, puis cette restauration de contrôle est supprimée. Aucun fichier actif n'est remplacé par `--verify`.

Pour restaurer réellement le système, suspendre les traitements, conserver l'état courant et réconcilier les envois postérieurs à la sauvegarde avant la reprise. Restaurer aveuglément une ancienne base peut perdre des preuves d'envoi et permettre un doublon. Aucune restauration en production ni purge automatique n'est déclenchée par ce script.

## Chemins conservés

Le CV actif reste `output/pdf/Naoufel_Chahid_CV_Francais_Candidatures.pdf`. La base, les comptes, les journaux actifs et les verrous restent sous `data/candidatures/`. Le cron, le service utilisateur et Chrome utilisent les mêmes lanceurs et chemins absolus.

## Git local

Le code, les guides et les contenus éditoriaux non privés sont versionnés localement. Les fichiers `.env*` privés, CV, exports de profil, comptes, bases, journaux, copies préparatoires et sauvegardes sont exclus. `.env.example`, `.env.candidatures.example` et `.env.playwright.example` restent des modèles sans secret. Aucun dépôt distant n'est ajouté automatiquement.
