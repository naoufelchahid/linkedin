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
