# Graphe 1 — découverte et qualification des offres

Le projet actif est [jobs/graphe1/](jobs/graphe1/README.md). Il découvre les offres, qualifie leurs missions à partir du CV confirmé et produit les rapports de revue privés.

```bash
cd jobs/graphe1
uv run --locked linkedin-discovery doctor
uv run --locked linkedin-discovery status
```

Le code, les dépendances verrouillées, les tests et les fichiers de déploiement sont regroupés dans ce dossier. La configuration privée est `jobs/graphe1/.env`. La base et les rapports restent sous `data/candidatures/discovery/`, accessibles par `jobs/graphe1/var`. Le CV confirmé conserve son chemin existant.

Les points d’entrée `jobs/decouverte.py` et `python -m src.candidatures.discovery` restent compatibles. Les seuls tests à la racine vérifient cette compatibilité ; les tests métier et d’exploitation sont dans le package.

```bash
jobs/graphe1/.venv/bin/python -m pytest -q
```

Lire le [guide d’exploitation](jobs/graphe1/docs/exploitation.md) pour les sauvegardes et reprises. Le [plan de réorganisation](jobs/graphe1/docs/reorganisation.md) conserve les nettoyages et l’emplacement des éléments retirés. L’historique Git est conservé.
