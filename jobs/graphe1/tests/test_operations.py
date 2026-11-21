"""Contrats d’installation, configuration, sauvegarde et exploitation."""

import io
import json
import sqlite3
import tarfile
from pathlib import Path

import pytest
import requests

from linkedin_discovery.adapters.apify import Apify
from linkedin_discovery.cli import main
from linkedin_discovery.config import Config
from linkedin_discovery.errors import ConnectorError
from linkedin_discovery.maintenance import backup_state, verify_backup
from linkedin_discovery.prompts import qualification_prompt
from linkedin_discovery.store import Store
from linkedin_discovery.workflow import DiscoveryService


def test_configuration_resolves_relative_paths_from_home(tmp_path, monkeypatch):
    monkeypatch.delenv("DISCOVERY_CV", raising=False)
    monkeypatch.delenv("DISCOVERY_DATA_DIR", raising=False)
    monkeypatch.delenv("DISCOVERY_PROMPT_FILE", raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "APIFY_TOKEN=secret\nLANGSMITH_API_KEY=private\nDISCOVERY_CV=cv.pdf\nDISCOVERY_DATA_DIR=runtime\nDISCOVERY_PROMPT_FILE=prompt.txt\n"
    )
    config = Config.load(tmp_path)
    assert config.cv == tmp_path / "cv.pdf"
    assert config.data == tmp_path / "runtime"
    assert config.prompt_file == tmp_path / "prompt.txt"
    assert "secret" not in repr(config)
    assert "private" not in repr(config)
    assert env.stat().st_mode & 0o777 == 0o600


def test_packaged_prompt_does_not_require_design_document(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    prompt = qualification_prompt()
    assert "Ignore tous les prérequis" in prompt
    assert "Contrat de lecture v2" in prompt
    assert len(prompt.splitlines()) == 2


def test_daily_schedule_reuses_cycle_without_new_collection(tmp_path):
    service = DiscoveryService(Config(root=tmp_path), apify=object(), codex=object())
    original = service.create
    service.create = lambda: original(cv_data=(b"%PDF-test", "GraphRAG"), prompt="missions")
    try:
        with service.store.locked():
            first = service.daily_cycle()
            assert service.daily_cycle() == first
        assert service.store.db.execute("SELECT count(*) FROM cycles").fetchone()[0] == 1
    finally:
        service.store.close()


def test_backup_includes_database_reports_and_validation_receipts(tmp_path):
    store = Store(tmp_path / "var")
    try:
        cycle = store.create_cycle(b"%PDF-test", "GraphRAG", "missions", {})
        (store.data / "reports").mkdir()
        (store.data / "reports/report.html").write_text("<p>private report</p>")
        (store.data / "validations").mkdir()
        (store.data / "validations/receipt.json").write_text('{"decision":"accepted"}')
        result = backup_state(store, tmp_path / "backups")
        assert result["status"] == "verified"
        assert verify_backup(result["archive"])["files"] == 4
        assert Path(result["archive"]).stat().st_mode & 0o777 == 0o600
        with tarfile.open(result["archive"]) as tar:
            restored = tmp_path / "restored.sqlite3"
            restored.write_bytes(tar.extractfile("discovery.sqlite3").read())
        db = sqlite3.connect(restored)
        try:
            assert db.execute("SELECT id FROM cycles").fetchone()[0] == cycle
        finally:
            db.close()
    finally:
        store.close()


def test_backup_refuses_recursive_destination(tmp_path):
    store = Store(tmp_path / "var")
    try:
        with pytest.raises(ValueError, match="backup_destination_inside_state"):
            backup_state(store, store.data / "backups")
    finally:
        store.close()


def test_backup_rejects_path_traversal(tmp_path):
    path = tmp_path / "unsafe.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        data = b"{}"
        entry = tarfile.TarInfo("../escape")
        entry.size = len(data)
        tar.addfile(entry, io.BytesIO(data))
    with pytest.raises(ValueError, match="backup_integrity_failed"):
        verify_backup(path)


def test_future_database_schema_is_refused(tmp_path):
    path = tmp_path / "discovery.sqlite3"
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version=99")
    db.close()
    with pytest.raises(RuntimeError, match="database_schema_version_unsupported"):
        Store(tmp_path)


def test_status_and_doctor_do_not_start_external_jobs(tmp_path, capsys):
    code = main(["--home", str(tmp_path), "doctor"])
    assert code == 2
    assert json.loads(capsys.readouterr().out)["apify_configured"] is False
    assert main(["--home", str(tmp_path), "status"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "empty"


class Session:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, kwargs))
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


class Response:
    def __init__(self, code):
        self.status_code = code
        self.ok = code == 200

    def json(self):
        return {"data": {"status": "SUCCEEDED"}}


def test_apify_get_retries_bounded_transient_failures(monkeypatch):
    monkeypatch.setattr("linkedin_discovery.adapters.apify.time.sleep", lambda _: None)
    api = Apify("secret")
    api.session = Session([requests.Timeout("private URL"), Response(503), Response(200)])
    assert api.run("run")["status"] == "SUCCEEDED"
    assert len(api.session.calls) == 3


def test_apify_post_is_never_retried(monkeypatch):
    monkeypatch.setattr("linkedin_discovery.adapters.apify.time.sleep", lambda _: None)
    api = Apify("secret")
    api.session = Session([requests.Timeout("private URL")])
    with pytest.raises(ConnectorError, match="apify_network_error"):
        api.start("consultant IA", 100)
    assert len(api.session.calls) == 1


def test_failed_get_does_not_leak_network_error_details(monkeypatch):
    monkeypatch.setattr("linkedin_discovery.adapters.apify.time.sleep", lambda _: None)
    api = Apify("secret")
    api.session = Session([requests.Timeout("secret")] * 3)
    with pytest.raises(ConnectorError) as error:
        api.run("run")
    assert str(error.value) == "apify_network_error"


@pytest.mark.parametrize("strict,expected", [(False, 0), (True, 3)])
def test_automation_can_fail_on_partial_results_without_changing_legacy_exit(
    tmp_path, monkeypatch, capsys, strict, expected
):
    from types import SimpleNamespace

    from linkedin_discovery import cli

    class Service:
        def __init__(self, _config):
            self.store = SimpleNamespace(close=lambda: None)

        def run(self, cycle_id):
            return {"cycle_id": cycle_id, "status": "collected"}

        def status(self, _cycle_id):
            return {"qualifications": {"done": 2, "error": 1}}

    monkeypatch.setattr(cli, "DiscoveryService", Service)
    args = ["--home", str(tmp_path), "resume", "cycle"]
    if strict:
        args.append("--fail-on-errors")
    assert cli.main(args) == expected
    assert json.loads(capsys.readouterr().out)["qualification_counts"]["error"] == 1
