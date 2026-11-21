"""Les anciens imports et le lanceur utilisent le package canonique."""
from pathlib import Path


def test_legacy_api_reuses_standalone_implementation():
    from src.candidatures.discovery.workflow import Pilot as LegacyPilot
    from linkedin_discovery.workflow import DiscoveryService
    from src.candidatures.discovery.model import normalize as legacy_normalize
    from linkedin_discovery.model import normalize
    assert LegacyPilot is DiscoveryService
    assert legacy_normalize is normalize


def test_legacy_config_keeps_existing_state_location():
    from src.candidatures.discovery.config import Config, ROOT
    config = Config.load()
    assert config.data == (ROOT / 'data/candidatures/discovery').resolve()


def test_legacy_config_uses_canonical_home_for_relative_paths(tmp_path, monkeypatch):
    from src.candidatures.discovery.config import Config
    monkeypatch.delenv('DISCOVERY_CV', raising=False)
    monkeypatch.delenv('DISCOVERY_DATA_DIR', raising=False)
    home = tmp_path / 'jobs/graphe1'
    home.mkdir(parents=True)
    (home / '.env').write_text('DISCOVERY_CV=cv.pdf\nDISCOVERY_DATA_DIR=var\n')
    config = Config.load(tmp_path)
    assert config.cv == home / 'cv.pdf'
    assert config.data == home / 'var'
