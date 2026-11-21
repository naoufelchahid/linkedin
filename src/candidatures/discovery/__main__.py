"""Ancienne commande, déléguée au package autonome du graphe 1."""
from pathlib import Path
import sys

from linkedin_discovery.cli import entrypoint as standalone_entrypoint
from linkedin_discovery.cli import main as standalone_main

HOME = Path(__file__).resolve().parents[3] / 'jobs/graphe1'


def main(argv=None):
    return standalone_main(['--home', str(HOME), *(sys.argv[1:] if argv is None else argv)])


def entrypoint():
    standalone_entrypoint(['--home', str(HOME), *sys.argv[1:]])


if __name__ == '__main__':
    entrypoint()
