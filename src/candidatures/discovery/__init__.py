"""Compatibilité avec le pilote ; le code canonique est dans jobs/graphe1/."""
from importlib.util import find_spec
from pathlib import Path
import sys

if find_spec('linkedin_discovery') is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'jobs/graphe1/src'))
