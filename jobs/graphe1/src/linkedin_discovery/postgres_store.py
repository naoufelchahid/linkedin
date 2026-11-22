"""Connexion du graphe 1 au schéma migré par le rôle d’administration."""

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import set_json_loads


class PostgresConnection:
    def __init__(self, dsn):
        self.connection = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        self.connection.execute("SET search_path TO pg_catalog, discovery")
        # Les lecteurs communs des snapshots et annonces attendent le JSON sérialisé.
        set_json_loads(lambda data: bytes(data).decode(), self.connection)

    def execute(self, sql, args=()):
        return self.connection.execute(sql.replace("?", "%s"), args)

    def executemany(self, sql, records):
        with self.connection.cursor() as cursor:
            cursor.executemany(sql.replace("?", "%s"), records)

    def transaction(self):
        return self.connection.transaction()

    def close(self):
        self.connection.close()
