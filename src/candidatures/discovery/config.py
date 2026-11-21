"""Conservation des chemins du pilote pour les anciens appelants."""
from dataclasses import dataclass, replace
from pathlib import Path

from linkedin_discovery.config import Config as StandaloneConfig
from linkedin_discovery.config import DEFAULT_PROFILES

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Config(StandaloneConfig):
    root: Path = ROOT
    cv: Path | None = ROOT / 'chahid naoufel CV.pdf'

    @classmethod
    def load(cls, root=ROOT):
        root = Path(root).resolve()
        config = StandaloneConfig.load(root=root / 'jobs/graphe1', env_file=root / 'jobs/graphe1/.env')
        return replace(config, root=root,
                       data_dir=config.data_dir or root / 'data/candidatures/discovery',
                       cv=config.cv or root / 'chahid naoufel CV.pdf')

    @property
    def data(self):
        return (self.data_dir or self.root / 'data/candidatures/discovery').resolve()
