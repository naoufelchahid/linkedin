"""Les tests de candidature utilisent l’environnement verrouillé du graphe 2."""

import pytest

pytest.importorskip(
    "linkedin_applications",
    reason="Exécuter les tests du graphe 2 avec jobs/graphe2/.venv/bin/python.",
)
