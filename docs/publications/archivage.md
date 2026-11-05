# Archives des publications

Chaque publication confirmée possède un dossier sous `posts/published/AAAA/MM/identifiant/`. L'archivage automatique est intégré à la CLI depuis le 5 novembre 2026.

## Publication et reprise

1. Valider humainement le texte, les assets et le destinataire, puis contrôler avec `dry-run`.
2. La commande `publish --confirm-publish` réserve une tentative dans `data/publications/state.sqlite3` et fige l'image éventuelle avant l'appel distant.
3. Après réponse avec un URN de publication valide, conserver le reçu en base puis exporter le texte exact, le destinataire, la date UTC, l'URN et les assets.
4. En cas d'échec d'export, le reçu reste en base et `archived: false` signale la reprise nécessaire. La commande `archive` ci-dessous ne publie rien.
5. Retirer ensuite le brouillon de la file éditoriale active, en conservant toute variante utile comme document historique. Ce déplacement du fichier source reste manuel pour préserver ses références.

```bash
python3 src/api/linkedin_client.py archive
```

Une relance avec le même contenu, auteur, image et texte alternatif après succès reprend l'archive sans nouvel envoi. Une tentative interrompue ou sans URN reste « à vérifier » et bloque tout renvoi automatique identique. Le POST de publication n'est jamais automatiquement réessayé après un timeout ou un 5xx. Toute résolution d'un résultat incertain exige de vérifier l'état réel sur LinkedIn.

Ces garanties concernent la CLI du workflow. Les méthodes bas niveau `LinkedInAPI.create_*` restent des primitives HTTP : ne pas les utiliser directement pour contourner le journal.

## Contenu d'une archive

```text
posts/published/AAAA/MM/identifiant/
  post.md              # contenu et métadonnées
  texte-publie.txt      # commentaire exact envoyé, suivi d'un retour à la ligne
  publication.json     # auteur, URN, date, réponse API et empreintes
  assets/              # image et texte alternatif, le cas échéant
```

Les fichiers existants doivent avoir un contenu identique : aucune archive n'est écrasée silencieusement. Les statistiques datées sont enregistrées séparément sous `data/publications/stats/` ; leur collecte et leur classement restent manuels.

## Import des trois anciennes publications

Les trois documents et leurs assets ont été regroupés à partir des archives locales existantes. Leurs métadonnées originales sont conservées. `publication.json` indique `source: existing_local_archive`, l'absence de reçu API historique et l'absence de nouvelle vérification distante ; l'auteur manquant n'est pas inventé. Ces imports ne créent pas rétroactivement de tentative dans le nouveau journal.

Le document Jev contient une date de brouillon postérieure à la date de publication enregistrée. Cette incohérence reste signalée. Sa copie de brouillon est classée sous `posts/archives/legacy/published-drafts/` et ne constitue plus un nouveau contenu à publier.

## Sources et confidentialité

Les anciens guides et imports sont sous `posts/archives/legacy/`. Les brouillons abandonnés peuvent être classés sous `posts/archives/abandoned/`, sans statut publié. Une archive de publication ne contient aucun CV, compte employeur ou dossier de candidature.

La copie préparatoire d'image sous `data/publications/outbox/` permet de reprendre l'export exact ; elle reste hors Git. Le journal SQLite et les archives font partie de la [sauvegarde du projet](../maintenance.md).
