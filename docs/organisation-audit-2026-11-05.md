> Document historique : audit avant rangement. Pour l’état installé, lire [organisation.md](organisation.md).

# Audit du dossier et propositions d'organisation

Audit local du 5 novembre 2026. Les contenus privés n'ont pas été recopiés dans ce rapport. **La documentation est corrigée ; les déplacements et développements ci-dessous restent proposés.**

## Diagnostic

Les deux moteurs sont déjà séparés dans le code : `src/api/linkedin_client.py` pour les publications et `src/candidatures/` pour les dossiers. La confusion provient surtout du classement des sources, de la documentation et de l'archivage.

| Constat vérifié | Conséquence | Proposition |
| --- | --- | --- |
| Le README et AGENTS décrivaient principalement la publication, avec Ads et analytics | Périmètre ambigu ; fonctions annoncées mais absentes | Deux entrées documentaires, sans troisième processus Ads — corrigé |
| `src/ads/`, `src/analytics/`, `data/stats/` sont vides | Des dossiers donnent l'impression de fonctionnalités disponibles | Retirer les deux modules vides lors du rangement ; classer les futures statistiques sous publications |
| 18 fichiers Markdown dans `posts/drafts/`, dont un travail sur le profil, des notes et une ressource | « drafts » ne signifie pas toujours « post à publier » | Séparer posts, travail sur le profil et ressources éditoriales |
| Trois publications archivées avec URN, date et assets existants | Bonne base, mais classement manuel et pas de reçu généré automatiquement | Un dossier d'archive par publication, avec contenu exact et preuve |
| Le texte Jev existe à la fois dans drafts et published ; l'image est dupliquée | Risque de traiter une ancienne publication comme nouvelle | Retirer cette copie de la file active après rapprochement, conserver une archive de référence |
| `cases.payload` est remplacé lors d'une révision ; `attempts` garde une version et un reçu, pas le dossier complet | Historique des anciennes réponses incomplet | Instantanés de versions et export privé par candidature |
| Les rapports de candidatures mélangeaient des étapes bloquées et le succès final | Un lecteur pouvait croire Telegram ou Chrome encore indisponible | État courant dans l'exploitation ; étapes passées identifiées comme historiques — corrigé |
| CV, exports de profil, positionnement, image et guides importés sont à la racine | Sources difficiles à distinguer des documents actifs | Classer les références et les imports, avec un manifeste de migration |
| `data/candidatures/` contient état, comptes, logs et résultats de tests | Données de production et diagnostics mélangés | Séparer archives, diagnostics et logs ; conserver les fichiers actifs à leur emplacement tant que les chemins ne sont pas migrés |
| Pas de dépôt Git initialisé | Aucun historique Git ni retour arrière par commit | Initialiser Git après contrôle des exclusions et des données personnelles |

### Doublons et incohérences précis

Doublons binaires vérifiés par empreinte, hors secrets et données privées :

- `about.json` et `about_en.json` sont identiques.
- `message-demarrage (1).txt` et `linkpost-quatre-formats-pack (1)/DEMARRAGE.txt` sont identiques.
- `posts/drafts/assets/jev.jpg` et `posts/published/assets/jev.jpg` sont identiques.
- Après retrait des métadonnées, le texte de `posts/published/2026-09-22_nouveaute_modele_decision_jev.md` est identique au fichier homonyme dans drafts.

Le document Jev porte une date de brouillon au 22 septembre et une date de publication au 21 septembre. Le nom du fichier ne doit donc pas servir à déduire la date effective. Vérifier cette métadonnée avant de renommer l'archive ; ne pas la corriger par supposition.

Le client de publication lit intégralement `--file`. Les en-têtes YAML des archives et les notes éditoriales ne sont pas supprimés par le code. Le guide impose désormais un fichier de texte publiable distinct ; un extracteur contrôlé serait une amélioration utile.

## Option A — séparation progressive recommandée

Conserver les interfaces qui fonctionnent, clarifier les dossiers et ajouter l'archivage manquant. Le code et les archives sont séparés par processus, sans déplacer la base en activité.

Arborescence cible proposée :

```text
README.md                         # portail des deux processus
AGENTS.md                         # règles et choix du processus
CONTEXT.md                        # vocabulaire des deux domaines
memoire-linkedin.md               # source éditoriale canonique attendue par le skill
src/
  api/linkedin_client.py          # publications, chemin conservé
  candidatures/                   # offres, dossiers, validations et envois
docs/
  publications/                   # workflow et archivage
  candidatures/                   # workflow, exploitation, règles et archivage
  adr/                            # décisions techniques, avec périmètre explicite
  organisation.md
references/
  publications/
    positionnement/
    strategie/
    profil/
posts/
  drafts/                         # contenus réellement en préparation
  published/AAAA/MM/identifiant/  # archive des publications confirmées
  archives/
    abandoned/                    # brouillons abandonnés
    legacy/                       # anciens guides, imports et variantes classées
data/
  publications/
    research/
    stats/
  candidatures/                   # intégralement privé, hors Git
    state.sqlite3                 # état courant et déduplication
    candidate_facts.json
    accounts.md                   # identifiants, séparés des archives de dossiers
    references/cv/                # originaux et anciennes variantes
    archives/AAAA/identifiant/    # versions, décisions, CV et reçus
    diagnostics/                  # essais utiles conservés, datés
    logs/
output/pdf/                       # CV actif conservé ici pendant la transition
scripts/
tests/
tmp/                              # rendus temporaires, aucune source canonique
```

Cette option conserve le chemin du CV actif, `src/candidatures`, les lanceurs et la base. Les déplacements vers `logs/`, `diagnostics/` et les archives demandent encore des adaptations ciblées ; le diagramme n'est pas une description de l'état déjà installé.

`memoire-linkedin.md` reste une seule source canonique à la racine, car le skill actif l'attend à cet endroit. Les stratégies et exports peuvent être déplacés en mettant à jour ses liens. Les données du candidat restent privées ; une symétrie visuelle des dossiers ne justifie pas de les ranger avec les contenus publiables.

## Option B — regroupement complet par métier

Créer deux ensembles `workflows/publications/` et `workflows/candidatures/`, chacun avec son code, ses références et ses archives ; la partie privée des candidatures est exclue de Git.

Avantage : navigation entièrement centrée sur les deux métiers. Coût : migration des imports Python, commandes, tests, chemins du skill, CV, scripts, cron, service utilisateur et configuration MCP. Les commandes actuelles devraient être conservées par des adaptateurs temporaires ou remplacées partout.

Je recommande **A** maintenant : le classement et l'archivage peuvent progresser sans refondre une automatisation qui vient d'être mise en service. B n'apporte pas de fonction métier supplémentaire à court terme.

## Classement proposé des fichiers actuels

| Fichiers actuels | Destination proposée, option A | Traitement |
| --- | --- | --- |
| `brief.json` | `references/publications/positionnement/` | Garder la source et actualiser les liens |
| `src/strategy/*.md` | `references/publications/strategie/` ; profil dans `profil/` | Sortir la documentation métier du code |
| `profile.json`, `about*.json` | `references/publications/profil/` | Identifier langue, source et date ; une seule copie pour les doublons exacts |
| `posts/drafts/2026-11-02_profil_linkedin_depuis_cv.md` | `references/publications/profil/` | Le classer comme travail sur le profil, sans conclure qu'il a été appliqué |
| `linkpost-quatre-formats-pack (1)/`, `message-demarrage (1).txt` | `posts/archives/legacy/linkpost/` | Conserver le pack importé ; le skill actif reste dans `.agents/skills/` |
| `prompt-memoire.txt` | `posts/archives/legacy/` après vérification des usages | Ne pas maintenir une deuxième règle éditoriale active |
| `Naoufel_Chahid_CV_Francais.pdf` et variante Contexte Lab | `data/candidatures/references/cv/` | Conserver les versions, mettre à jour les références documentaires |
| PDF `..._Candidatures.pdf` | Emplacement actif inchangé pendant le premier lot | Toute migration ultérieure doit préserver son empreinte et adapter `Config.cv` |
| `data/research/` et `data/stats/` | `data/publications/research/` et `stats/` | Mettre à jour les liens de la mémoire et des guides |
| `pilot-*.json`, ancien diagnostic Chrome | `data/candidatures/diagnostics/2026-11-05/` | Privé ; ne pas les confondre avec des archives complètes |
| `1788427642790.jpeg` | À identifier avant classement | Le nom seul ne permet pas d'en déterminer l'usage |
| `tmp/` | Temporaire | Ne purger qu'après identification de toute pièce encore utile |

Aucun fichier n'est supprimé dans cette phase d'analyse. Un doublon n'est retiré qu'après vérification des références vers la copie retenue.

## Deux archivages, deux contrats

| | Publications | Candidatures |
| --- | --- | --- |
| Archive métier | Contenu exact publié, assets, date, compte, URN, reçu et statistiques datées | Offre, chaque version de réponses/lettre/CV, décision, empreintes, tentatives et confirmation |
| Déclencheur | Publication effectivement confirmée | Chaque révision importante, décision et tentative ; pas seulement un envoi réussi |
| Identifiant | URN LinkedIn associé à un identifiant local | Identifiant local du dossier et numéro de version |
| Emplacement cible A | `posts/published/` | `data/candidatures/archives/` |
| Accès | Contenus publics publiés ; références internes à distinguer | Privé, hors Git ; URLs de confirmation comprises |
| État actuel | Manuel, trois documents présents | Base opérationnelle ; export complet non implémenté |

L'archivage n'efface jamais la mémoire de déduplication. Les comptes et secrets sont conservés séparément ; une sauvegarde cohérente protège les archives, mais ne les remplace pas.

## Ordre de réalisation proposé

1. **Documentation — réalisé dans cet audit.** Deux parcours, deux guides d'archivage, README et AGENTS recentrés, glossaire élargi, états historiques clarifiés. Les liens locaux sont vérifiés.
2. **Rangement sans changement d'exécution.** Produire un manifeste ancien chemin → nouveau chemin avec empreintes, classer les références et imports, rapprocher les doublons, corriger tous les liens. Conserver CV actif, base, comptes, verrous et lanceurs en place.
3. **Archivage effectif.** Ajouter les instantanés des versions de candidature et leurs exports privés. Ajouter le reçu et le classement de publication, avec extraction contrôlée du texte sans métadonnées. Vérifier qu'un archivage échoué ne provoque jamais une seconde publication ou candidature.
4. **Versionnement et sauvegarde.** Contrôler les exclusions des CV, exports personnels, comptes et tokens avant initialisation Git. Ajouter une sauvegarde cohérente de SQLite et des archives privées. Tester la restauration avant de définir une purge.

Une migration qui touche finalement un chemin utilisé par le cron, le service, MCP ou le CV exige une fenêtre contrôlée : aucune soumission en cours, sauvegarde cohérente, adaptation de toutes les références, vérification puis reprise. Le rangement ne doit ni retirer une approbation valide ni rejouer un envoi confirmé.

## Vérification de cet audit

Les 54 liens locaux des 12 documents créés ou modifiés ont été vérifiés : aucune cible manquante. Une copie préalable des documents existants est conservée dans `tmp/docs-before-organisation-20261105T143523Z/`.

Inventaire des chemins et doublons par empreinte ; lecture du client de publication, du modèle d'état et des guides ; contrôle des métadonnées et assets des trois publications ; lecture seule des états SQLite. Au moment de l'audit : un dossier `sent` et un `blocked`. Aucun appel de publication, aucune recherche d'offres et aucun envoi n'ont été déclenchés par ce travail documentaire.
