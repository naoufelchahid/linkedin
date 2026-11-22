# Import PostgreSQL des collectes Apify

Configurer la connexion cible avec les paramètres libpq (`PGSERVICE` ou `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, et `.pgpass` pour le mot de passe). À la création de la base, exécuter depuis la racine avec son administrateur :

```sh
psql -Xf db/bootstrap.sql
```

Attribuer `linkedin_migrator` au compte de déploiement et `linkedin_discovery` au compte d’import avec `GRANT`. Les deux rôles de groupe sont créés sans identifiants de connexion. Depuis le compte de déploiement, appliquer les migrations versionnées :

```sh
psql -Xf db/migrate.sql
```

Depuis le compte d’import, charger le tableau JSON d’un dataset Apify exporté. Fournir les mêmes identifiants de cycle et de recherche au rejeu.

```sh
uv sync --project jobs/graphe1 --locked
jobs/graphe1/.venv/bin/python -m linkedin_discovery.postgres_import \
  --cycle cycle-001 --profile analyste dataset.json
```

Une occurrence est identifiée par cycle, recherche et empreinte SHA-256 de la représentation texte du JSONB source. Elle conserve le document JSONB complet et les six colonnes métier. Une modification du document produit une nouvelle occurrence. Un objet sans identité exploitable garde son JSON et son erreur technique. Chaque import est transactionnel. Le module reprend les règles du graphe 1 pour l’identité et la version de l’annonce.

La recette `db/tests/apify_replay.sh` requiert Docker, les clients PostgreSQL et l’environnement Python installé ci-dessus. Elle crée un conteneur PostgreSQL 17 sur un port local aléatoire, rejoue les migrations et les données puis supprime le conteneur et son volume.

### CV figé par cycle

Sur le worker du graphe 1, définir `DISCOVERY_POSTGRES_DSN` dans sa configuration privée, par exemple `service=linkedin_discovery`. Appliquer le bootstrap et les migrations ci-dessus. Chaque création de cycle via la CLI ou Studio publie les octets du PDF confirmé, son SHA-256, son Markdown et sa provenance. Le graphe qualifie les offres avec ce Markdown. Un rejeu résout le PDF et le Markdown du cycle source dans PostgreSQL. Les cycles SQLite historiques restent lisibles depuis leurs snapshots.

`discovery.cycle_cv` associe le cycle à `documents.cv_versions.sha256`. La fonction Python `linkedin_discovery.documents.cycle_cv(dsn, cycle_id)` retourne les octets PDF et le Markdown, ou `None` pour un cycle sans association. La recette ci-dessus publie deux PDF synthétiques sous le même nom, supprime la source et le premier snapshot local, puis rejoue le premier cycle.

### Contrat des offres retenues

La vue `api.offres_retenues_v1` expose une ligne par couple `(cycle_id, identity)`. Le rôle de groupe `linkedin_selection` donne accès en lecture à cette vue. La colonne `identity` conserve l’URL canonique de la page ou, pour les annonces sans URL, leur clé d’ingestion. `version_id` identifie le contenu normalisé figé dans `content` (JSONB). `canonical_url` vaut NULL pour les annonces sans URL. `cv_sha256` désigne le PDF du cycle.

Dans chaque cycle, la version la plus récente l’emporte, avec départage par identifiant croissant à date identique. La dernière correction individuelle de cette version détermine le verdict applicable. À défaut, la vue utilise le verdict de qualification. Seul le verdict `retenir` apparaît. Le champ booléen `incertitude` garde la valeur de la qualification, éventuellement NULL en son absence. Une validation globale du rapport ne crée aucune correction individuelle.

La recette `db/tests/apify_replay.sh` compare les huit colonnes à la sélection SQLite par cycle sur des cas synthétiques. Pour ajouter la comparaison historique, fournir dans `RESTORED_DISCOVERY_SQLITE` le chemin de `restored/discovery/discovery.sqlite3` issu de la restauration du #1. La recette ouvre la copie SQLite en lecture seule et annule la transaction de comparaison en PostgreSQL. Elle affiche uniquement les compteurs par cycle.

Les tables `applications.submission_attempts` et `applications.submission_receipts` relient le dossier et la génération du tour aux versions de l’annonce, du CV et de la lettre. Le statut `transmitting` sans reçu impose une vérification après interruption. L’expiration du bail interdit les écritures du tour et maintient son exclusivité. Le worker peut libérer la tentative lorsque le tour se termine avant transmission. Une preuve positive relue sur le portail peut confirmer une tentative expirée. La transaction de confirmation conserve un reçu par dossier avant le checkpoint LangGraph. La recette se lance avec `db/tests/application_lots.sh`.

## Répétition de migration et retour arrière

Depuis la racine, fournir au lanceur le répertoire du bundle déjà restauré par #1. Le lanceur utilise l’environnement verrouillé G2 et ajoute les sources G1 à son chemin d’importation. Il crée un PostgreSQL privé sans interface réseau, avec un socket dans un répertoire temporaire. Les fichiers de la référence et de la copie sont ouverts en lecture seule.

```bash
export PLAYWRIGHT=/chemin/vers/node_modules/playwright
export CHROME=/chemin/vers/chrome
export THUNDERBIRD=/chemin/vers/thunderbird
export THUNDERBIRD_MCP_REPO=/chemin/vers/thunderbird-mcp
db/tests/migration_rehearsal.sh /chemin/vers/bundle-ticket-01
```

L’import transactionnel préserve en SQL les faits de découverte et la sélection par cycle. Le document partagé contient les octets du CV original et le Markdown dérivé. Les cycles gardent chacun le texte historique utilisé pour leur qualification. Les pièces du bundle et les anciennes bases sont aussi archivées dans une table privée pour reconstruire la copie à l’octet près.

Chaque dossier importé possède sa version, ses pièces et un lien vers le thread ancien. Les lots de recette et de production ont des identités distinctes. Des checkpoints anciens utilisent le même thread pour ces deux modes. L’historique conserve les questions, les réponses et leurs restrictions, les opérations et leurs preuves. Les anciens identifiants Telegram, les décisions de portée manquantes et les résultats d’opérations incertains restent tels quels. Les lignes dans `applications.legacy_holds` écartent les dossiers hérités de la file exécutable pendant le rapprochement individuel. Une reprise opérationnelle de ces dossiers requiert un état et une décision de reprise explicites.

Lors de la répétition du 22 novembre 2026, la copie a livré 224 versions, 640 observations Apify, six rapports, 244 tentatives de qualification et un accord global. La file comportait deux lots, douze associations aux lots, dix états de dossier, quatorze questions, neuf réponses, une réponse mémorisée, vingt-quatre tentatives historiques et zéro reçu de dépôt. Les dix derniers états comptaient cinq attentes, trois préparations et deux blocages. Les 130 checkpoints et les quatre PDF figuraient dans les 25 fichiers dont les empreintes sont vérifiées à l’aller et au retour.

Un dossier synthétique distinct traverse le graphe depuis son lot SQL dans un espace réseau limité au loopback. Une approbation de recette autorise le compte, le pilote Chrome utilise le code du message synthétique de Thunderbird, puis le worker reprend le formulaire. Le portail HTTP de recette vérifie les octets exacts du CV et conserve sa preuve avant l’interruption injectée. Un second Runner retrouve le reçu. Le collecteur local vérifie les champs des traces et l’absence des témoins privés. Le rollback reconstruit d’abord la référence ; le dossier et son nouveau reçu sont ensuite reportés dans la copie SQLite. Le worker de la révision antérieure vérifie son statut déjà soumis. Le parcours utilise des adaptateurs synthétiques pour le portail et le geste de dépôt.
