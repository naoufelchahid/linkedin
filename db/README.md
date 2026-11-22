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
