# Graphe 1

Le projet autonome est dans [graphe1/](graphe1/README.md) : code, dépendances verrouillées, configuration privée, tests et accès à la base.

```bash
cd graphe1
uv run --locked linkedin-discovery doctor
uv run --locked linkedin-discovery status
```

Le lanceur `decouverte.py` reste disponible pour les anciens appels. Les liens `.env` et `.venv` à la racine pointent vers la configuration et l’environnement uniques du projet.
