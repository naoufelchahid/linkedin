"""Vérifie la configuration réellement transmise au worker Codex."""
import json
from pathlib import Path
import runpy
import pytest

from src.candidatures import agent as module
from src.candidatures.agent import Agent, obj
from src.candidatures.config import Config


def test_worker_uses_playwright_extension_without_forwarding_secrets(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    (home / '.codex').mkdir(parents=True)
    config_file = home / '.codex/config.toml'
    config_file.write_text('[mcp_servers.node_repl]\ncommand="old-browser"\n'
                           '[mcp_servers.playwright]\ncommand="npx"\n'
                           '[mcp_servers.linkedin]\ncommand="uvx"\n'
                           '[mcp_servers.unrelated]\ncommand="other"\n')
    original = config_file.read_bytes()
    monkeypatch.setattr(Path, 'home', lambda: home)
    monkeypatch.setattr(Config, 'codex', property(lambda self: '/existing/codex'))
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'must-not-reach-worker')
    (Config(root=tmp_path).data / 'candidate_facts.json').write_text(json.dumps({
        'availability': {'statement': 'Disponible immédiatement, sans préavis',
                         'source': 'Confirmation explicite du candidat'}}))
    captured = {}

    class Process:
        returncode = 0

        def __init__(self, cmd, **kwargs):
            captured.update(cmd=cmd, kwargs=kwargs)
            self.output = Path(cmd[cmd.index('--output-last-message') + 1])

        def communicate(self, prompt, timeout):
            captured['prompt'] = prompt
            self.output.write_text('{"ok":true}')

    monkeypatch.setattr(module.subprocess, 'Popen', Process)
    assert Agent(Config(root=tmp_path)).run('test', obj({'ok': {'type': 'boolean'}})) == {'ok': True}
    cmd = captured['cmd']
    overrides = dict(cmd[i+1].split('=', 1) for i, arg in enumerate(cmd) if arg == '-c')
    assert overrides['mcp_servers.node_repl.enabled'] == 'false'
    assert overrides['mcp_servers.unrelated.enabled'] == 'false'
    assert 'mcp_servers.playwright.enabled' not in overrides
    assert 'mcp_servers.linkedin.enabled' not in overrides
    args = json.loads(overrides['mcp_servers.playwright.args'])
    assert '--extension' in args
    assert args[args.index('--browser') + 1] == 'chrome'
    output_dir = Path(args[args.index('--output-dir') + 1])
    assert output_dir.is_relative_to(tmp_path / 'data/candidatures')
    assert not output_dir.parent.exists()  # Les artefacts temporaires sont supprimés.
    assert '--headless' not in args and '--cdp-endpoint' not in args
    assert captured['kwargs']['umask'] == 0o077
    assert 'TELEGRAM_BOT_TOKEN' not in captured['kwargs']['env']
    assert 'must-not-reach-worker' not in repr(cmd)
    assert 'Disponible immédiatement, sans préavis' in captured['prompt']
    assert 'ne valent jamais approbation' in captured['prompt']
    assert config_file.read_bytes() == original


def test_playwright_launcher_keeps_token_out_of_arguments(tmp_path, monkeypatch):
    namespace = runpy.run_path(str(Path(__file__).parents[1] / 'scripts/playwright-mcp'))
    main = namespace['main']
    main.__globals__['ROOT'] = tmp_path
    (tmp_path / '.env.playwright').write_text('PLAYWRIGHT_MCP_EXTENSION_TOKEN=fixture-secret\n')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'telegram-secret')
    monkeypatch.setenv('UNRELATED_API_KEY', 'other-secret')
    monkeypatch.setattr(namespace['sys'], 'argv', ['playwright-mcp', '-y', '@playwright/mcp@latest', '--extension'])
    monkeypatch.setattr(namespace['shutil'], 'which', lambda *args, **kwargs: '/existing/npx')
    captured = {}
    monkeypatch.setattr(namespace['os'], 'execve', lambda path, args, env: captured.update(path=path, args=args, env=env))
    monkeypatch.setattr(namespace['os'], 'umask', lambda value: None)
    main()
    assert captured['env']['PLAYWRIGHT_MCP_EXTENSION_TOKEN'] == 'fixture-secret'
    assert 'fixture-secret' not in repr(captured['args'])
    assert 'TELEGRAM_BOT_TOKEN' not in captured['env']
    assert 'UNRELATED_API_KEY' not in captured['env']


@pytest.mark.parametrize('chrome_ok', [True, False])
def test_doctor_reports_current_probe_not_previous_result(tmp_path, chrome_ok):
    from src.candidatures.service import Service

    class ProbeAgent:
        def probe(self):
            return {'linkedin_ok': True, 'chrome_ok': chrome_ok, 'notes': 'test'}

    service = Service(Config(root=tmp_path), agent=ProbeAgent())
    service.store.set_setting('probe_ok', str(not chrome_ok).lower())
    service.store.set_setting('last_probe', 'previous-probe')
    report = service.doctor(probe=True)
    assert report['connectors_verified'] == chrome_ok
    assert report['last_connector_probe'] != 'previous-probe'
    assert report['last_connector_probe'] == service.store.setting('last_probe')
