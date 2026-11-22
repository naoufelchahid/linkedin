"""Contrats de reprise, preuve, déduplication et revue du pilote isolé."""

import json
import os
from pathlib import Path

import pytest

from linkedin_discovery.config import Config
from linkedin_discovery.connectors import ConnectorError
from linkedin_discovery.model import canonical_url, checked_result, normalize, rank
from linkedin_discovery.report import sample
from linkedin_discovery.workflow import Pilot

CV = "Compétences : GraphRAG, architecture de solutions IA, Python."


def raw(ident="123", description="Construire des solutions IA avec GraphRAG.", **changes):
    return dict(
        id=ident,
        title="Architecte IA",
        companyName="Test",
        location="Casablanca, Morocco",
        description=description,
        url=f"https://www.linkedin.com/jobs/view/{ident}",
        postedDate="2026-11-20",
        **changes,
    )


def result(offer, **changes):
    return dict(
        id=offer["key"],
        verdict="retenir",
        incertitude=False,
        motif="Mission correspondant au CV.",
        mission_citee="GraphRAG",
        competence_cv="GraphRAG",
        probleme_donnees="",
        **changes,
    )


class FakeApify:
    def __init__(self, datasets=None, failed=False):
        self.datasets = datasets or [[raw()], [raw()], []]
        self.failed = failed
        self.started = []

    def start(self, profile, limit):
        self.started.append(profile)
        return dict(
            id=str(len(self.started)), status="RUNNING", defaultDatasetId=str(len(self.started))
        )

    def run(self, ident):
        return dict(
            id=ident,
            status="FAILED" if self.failed and ident == "3" else "SUCCEEDED",
            defaultDatasetId=ident,
        )

    def items(self, dataset, limit):
        return self.datasets[(int(dataset) - 1) % 3][:limit]


class FakeCodex:
    def __init__(self, invalid=False):
        self.calls = []
        self.invalid = invalid

    def qualify(self, offer, cv, prompt):
        self.calls.append((offer["key"], cv, prompt))
        return {} if self.invalid else result(offer)


@pytest.fixture
def pilot(tmp_path):
    config = Config(root=tmp_path, collect_seconds=0)
    p = Pilot(config, apify=FakeApify(failed=True), codex=FakeCodex())
    yield p
    p.store.close()


def create(pilot, prompt="missions only"):
    return pilot.create(cv_data=(b"%PDF-test", CV), prompt=prompt)


def test_graph_partial_failure_dedup_resume_and_private_report(pilot):
    ident = create(pilot)
    state = pilot.run(ident)
    assert state["status"] == "partial"
    assert len(pilot.apify.started) == 3
    assert len(pilot.codex.calls) == 1
    assert len(pilot.store.items(ident)) == 1
    path = Path(state["report_path"])
    original = path.read_bytes()
    assert "FAILED" in original.decode()
    assert path.stat().st_mode & 0o777 == 0o600
    assert (pilot.store.data / "discovery.sqlite3").stat().st_mode & 0o777 == 0o600
    pilot.run(ident)
    assert len(pilot.apify.started) == 3
    assert len(pilot.codex.calls) == 1
    assert path.read_bytes() == original


def test_three_attempts_budget_survives_resume(pilot):
    pilot.codex.invalid = True
    ident = create(pilot)
    pilot.run(ident)
    assert len(pilot.codex.calls) == 3
    assert pilot.store.items(ident)[0]["status"] == "error"
    pilot.run(ident)
    assert len(pilot.codex.calls) == 3


def test_interrupted_attempt_consumes_budget(pilot):
    ident = create(pilot)
    pilot.ingest(ident, "a", raw())
    version = pilot.store.pending_versions(ident)[0]
    q = pilot.store.qualification(pilot.store.cycle(ident), version["id"])
    assert pilot.store.start_attempt(q["id"]) == 1
    pilot.codex.invalid = True
    pilot.run(ident)
    assert len(pilot.codex.calls) == 2


def test_unknown_apify_start_is_never_repeated(pilot):
    def start(*args):
        pilot.apify.started.append("unknown")
        raise ConnectorError("apify_network_error")

    pilot.apify.start = start
    ident = create(pilot)
    pilot.run(ident)
    pilot.run(ident)
    assert len(pilot.apify.started) == 3
    assert all(
        row["status"] == "START_UNCERTAIN"
        for row in pilot.store.db.execute("SELECT status FROM runs")
    )


def test_attach_uncertain_run_checks_search_and_resumes_without_start(pilot, monkeypatch):
    ident = create(pilot)
    profile = pilot.config.profiles[0]
    pilot.store.execute(
        "INSERT INTO runs(cycle_id,profile,status) VALUES(?,?,'START_UNCERTAIN')",
        (ident, profile),
    )
    settings = json.loads(pilot.store.cycle(ident)["settings"])
    search = dict(keywords=profile, location="Rabat", datePosted="r604800", limit=settings["limit"])
    monkeypatch.setattr(pilot.apify, "actor_id", lambda actor: actor, raising=False)
    monkeypatch.setattr(pilot.apify, "run_input", lambda store_id: search, raising=False)
    original_run = pilot.apify.run
    monkeypatch.setattr(
        pilot.apify,
        "run",
        lambda run_id: {
            **original_run(run_id),
            "defaultKeyValueStoreId": "input",
            "actId": settings["actor"],
        },
    )
    with pytest.raises(ValueError, match="run_input_mismatch"):
        pilot.attach_run(ident, profile, "3")
    search["location"] = "Morocco"
    assert pilot.attach_run(ident, profile, "3")["run_id"] == "3"
    with pytest.raises(ValueError, match="run_attachment_not_needed"):
        pilot.attach_run(ident, profile, "3")
    pilot.collect({"cycle_id": ident})
    assert pilot.apify.started == list(pilot.config.profiles[1:])


def test_human_review_is_separate_and_report_immutable(pilot):
    ident = create(pilot)
    state = pilot.run(ident)
    path = Path(state["report_path"])
    content = path.read_bytes()
    pilot.store.review(state["report_id"], 1, "écarter", "Correction confirmée")
    item = pilot.store.items(ident)[0]
    assert item["effective_verdict"] == "écarter"
    assert item["result"]["verdict"] == "retenir"
    assert path.read_bytes() == content
    with pytest.raises(ValueError, match="report_item_not_found"):
        pilot.store.review(state["report_id"], 99, "retenir")


def test_cache_and_new_versions_do_not_inherit_human_review(pilot):
    first = create(pilot)
    state = pilot.run(first)
    pilot.store.review(state["report_id"], 1, "écarter")
    second = create(pilot)
    pilot.run(second)
    assert len(pilot.codex.calls) == 1
    third = create(pilot, "new prompt")
    pilot.run(third)
    assert len(pilot.codex.calls) == 2
    pilot.apify.datasets = [[raw(description="Nouvelle mission : GraphRAG et agents IA.")], [], []]
    pilot.run(first)
    assert len(pilot.codex.calls) == 3
    assert len(pilot.store.items(first)) == 1
    assert pilot.store.items(first)[0]["human_verdict"] is None
    assert pilot.store.items(second)[0]["human_verdict"] == "écarter"


def test_replay_exact_report_uses_saved_cv_and_no_apify(pilot):
    state = pilot.run(create(pilot))
    ident = pilot.replay(state["report_id"], prompt="corrected prompt")
    replay_state = pilot.run(ident)
    assert len(pilot.apify.started) == 3
    assert len(pilot.codex.calls) == 2
    assert pilot.codex.calls[-1][1] == CV
    assert len(pilot.store.items(ident)) == 1
    snapshot = json.loads(
        pilot.store.db.execute(
            "SELECT snapshot FROM reports WHERE id=?", (replay_state["report_id"],)
        ).fetchone()[0]
    )
    assert snapshot["source_cycle_id"] == state["cycle_id"]
    assert len(snapshot["runs"]) == 3
    assert any(run["status"] == "FAILED" for run in snapshot["runs"])


def test_unreadable_announcement_is_data_problem_not_rejection(pilot):
    pilot.apify.datasets = [[raw(description="")], [], []]
    ident = create(pilot)
    pilot.run(ident)
    item = pilot.store.items(ident)[0]
    assert item["status"] == "data_problem"
    assert item["effective_verdict"] is None
    assert not pilot.codex.calls


def test_fabricated_evidence_is_rejected_and_uncertain_acceptance_allowed():
    offer = normalize(raw())
    r = result(offer)
    assert checked_result(r, offer, CV) == r
    r["competence_cv"] = "invented experience"
    with pytest.raises(ValueError, match="skill_quote_not_in_cv"):
        checked_result(r, offer, CV)
    r.update(incertitude=True, mission_citee="", competence_cv="")
    assert checked_result(r, offer, CV)["verdict"] == "retenir"


def test_identity_uses_the_offer_page():
    first = normalize(
        raw(
            recruiterUrl="https://linkedin.com/in/one",
            requisitionId="REQ1",
            applyUrl="https://employer.example/apply",
        )
    )
    second = normalize(
        raw(
            recruiterUrl="https://linkedin.com/in/two",
            requisitionId="REQ1",
            applyUrl="https://employer.example/apply",
        )
    )
    assert first["key"] == second["key"]
    different_page = {
        **raw(),
        "url": "https://www.linkedin.com/jobs/view/456",
        "applyUrl": "https://employer.example/apply",
        "companyUrl": "https://linkedin.com/company/test",
    }
    distinct = normalize(different_page)
    assert first["key"] != distinct["key"]
    alternative = {
        **raw(),
        "url": "https://ma.linkedin.com/jobs/view/architecte-123?utm_source=job",
    }
    assert first["key"] == normalize(alternative)["key"]
    assert first["key"] != normalize({**raw(), "url": first["url"] + "?job=456"})["key"]
    assert first["deposit_key"] == second["deposit_key"]
    assert normalize(raw())["key"] == normalize(raw())["key"]


def test_rank_geography_then_remote_then_date():
    offers = [normalize(raw(str(i))) for i in range(5)]
    offers[0].update(location="Fès", work_mode="", posted_at="2026-11-20")
    offers[1].update(location="Morocco", work_mode="Remote", posted_at="2026-11-19")
    offers[2].update(location="Rabat", posted_at="2026-11-18")
    offers[3].update(location="Casablanca", posted_at="2026-11-20")
    offers[4].update(location="Rabat", posted_at="")
    assert sorted(offers, key=rank) == [offers[3], offers[2], offers[4], offers[1], offers[0]]


def test_sample_balanced_and_fallback():
    items = []
    for n in range(24):
        offer = normalize(raw(str(n)))
        r = result(offer)
        r.update(verdict="écarter" if n % 3 == 2 else "retenir", incertitude=n % 3 == 1)
        items.append(dict(status="done", offer=offer, result=r, version_id=str(n)))
    selected = sample(items)
    assert len(selected) == 15
    assert sum(i["result"]["verdict"] == "écarter" for i in selected) == 5
    assert sum(i["result"]["incertitude"] for i in selected) == 5
    assert len(sample(items[:4])) == 4
    assert len(sample([i for i in items if i["result"]["verdict"] == "écarter"])) == 8


def test_report_escapes_web_content(pilot):
    pilot.apify.datasets = [
        [raw(description="GraphRAG <script>alert(1)</script>", titleX="ignored")],
        [],
        [],
    ]
    state = pilot.run(create(pilot))
    html = Path(state["report_path"]).read_text()
    assert "<script>" not in html
    assert "default-src" in html


def test_lock_excludes_concurrent_execution(pilot):
    from linkedin_discovery.store import Store

    other = Store(pilot.store.data)
    try:
        with pilot.store.locked(), pytest.raises(RuntimeError, match="discovery_already_running"):
            with other.locked():
                pass
    finally:
        other.close()


def test_traces_only_contain_technical_metadata(pilot):
    class Trace:
        def __init__(self):
            self.runs = []

        def create_run(self, **kwargs):
            self.runs.append(kwargs)

    trace = Trace()
    pilot.tracer = trace
    pilot.run(create(pilot))
    assert trace.runs
    for r in trace.runs:
        assert r["inputs"] == r["outputs"] == {}
        assert set(r["extra"]["metadata"]) == {
            "cycle_id",
            "technical_id",
            "status",
            "duration_seconds",
        }
        assert CV not in str(r)


def test_detailed_traces_nest_graph_and_qualification_with_inputs_outputs(tmp_path, monkeypatch):
    from langsmith import Client

    captured = {}

    def create_run(self, name, inputs, run_type, **kwargs):
        captured[str(kwargs["id"])] = dict(name=name, inputs=inputs, **kwargs)

    def update_run(self, run_id, **kwargs):
        captured[str(run_id)].update(
            {key: value for key, value in kwargs.items() if value is not None}
        )

    monkeypatch.setattr(Client, "create_run", create_run)
    monkeypatch.setattr(Client, "update_run", update_run)
    config = Config(root=tmp_path, collect_seconds=0, langsmith_trace_content=True)
    p = Pilot(config, apify=FakeApify(), codex=FakeCodex())
    p.tracer = Client(api_key="test", auto_batch_tracing=False)
    try:
        state = p.run(create(p))
        assert state["qualification_counts"] == {"done": 1}
        root = next(r for r in captured.values() if r["name"] == "graphe1.discovery")
        qualification = next(r for r in captured.values() if r["name"] == "codex.qualification")
        assert root["inputs"]["cycle_id"] == state["cycle_id"]
        assert root["outputs"]["qualification_counts"] == {"done": 1}
        assert qualification["inputs"]["cv"] == CV
        assert qualification["inputs"]["annonce"]["description"] == raw()["description"]
        assert qualification["outputs"]["result"]["verdict"] == "retenir"
        assert qualification["parent_run_id"]
        assert str(qualification["trace_id"]) == str(root["id"])
        p.run(state["cycle_id"])
        assert len(p.codex.calls) == 1
        assert any(r["name"] == "qualification.cache" for r in captured.values())
        assert "codex_attempt" not in {r["name"] for r in captured.values()}
    finally:
        p.store.close()


def test_studio_graph_inspection_is_lazy_and_execution_closes_storage(tmp_path, monkeypatch):
    import asyncio

    from linkedin_discovery import studio

    config = Config(root=tmp_path, collect_seconds=0)
    setup = Pilot(config)
    ident = create(setup)
    setup.store.close()
    services = []

    def service(_config):
        p = Pilot(config, apify=FakeApify(), codex=FakeCodex())
        services.append(p)
        return p

    monkeypatch.setattr(studio, "DiscoveryService", service)

    async def run():
        async with studio.make_graph() as graph:
            assert {"collect", "qualify", "report"} <= set(graph.get_graph().nodes)
            assert services == []
            output = await graph.ainvoke({"cycle_id": ident})
            assert output["qualification_counts"] == {"done": 1}
            assert Path(output["report_path"]).exists()
            assert len(services) == 1
        async with studio.make_graph() as graph:
            with pytest.raises(ValueError, match="cycle_id_required"):
                await graph.ainvoke({})
        # Une nouvelle exécution reprend les résultats sans nouveau run Apify.
        async with studio.make_graph() as graph:
            output = await graph.ainvoke({"cycle_id": ident})
            assert output["qualification_counts"] == {"done": 1}
            assert services[-1].apify.started == []

    asyncio.run(run())


def test_data_problem_has_no_third_business_verdict():
    offer = normalize(raw())
    r = result(offer)
    r.update(
        verdict=None,
        incertitude=True,
        mission_citee="",
        competence_cv="",
        probleme_donnees="Source illisible",
    )
    assert checked_result(r, offer, CV)["verdict"] is None


def test_destination_preserves_requisition_query():
    assert (
        canonical_url("https://jobs.example/apply?jobId=123&utm_source=linkedin")
        == "https://jobs.example/apply?jobId=123"
    )
    assert canonical_url("javascript:alert(1)") == ""


def test_replay_detects_tampered_cv(pilot):
    state = pilot.run(create(pilot))
    cycle = pilot.store.cycle(state["cycle_id"])
    path = pilot.store.data / "snapshots" / (cycle["cv_hash"] + ".pdf")
    path.write_bytes(b"%PDF-modified")
    with pytest.raises(ValueError, match="saved_cv_integrity_failed"):
        pilot.replay(state["report_id"], prompt="changed")


def test_late_results_use_frozen_cycle_prompt_and_keep_report(pilot):
    state = pilot.run(create(pilot, prompt="frozen prompt"))
    original = Path(state["report_path"]).read_bytes()
    pilot.apify.datasets[1].append(raw("456"))
    later = pilot.run(state["cycle_id"])
    assert len(pilot.codex.calls) == 2
    assert pilot.codex.calls[-1][2] == "frozen prompt"
    assert len(pilot.store.items(state["cycle_id"])) == 2
    assert Path(state["report_path"]).read_bytes() == original
    assert later["report_id"] != state["report_id"]


def test_explicit_remote_in_description_without_inventing_mode():
    remote = normalize(
        raw(description="Construire GraphRAG. Télétravail possible.", workType="Engineering")
    )
    remote["location"] = "Fès"
    assert rank(remote)[0] == 1
    office = normalize(
        raw(description="GraphRAG sur site, sans télétravail.", workType="Engineering")
    )
    office["location"] = "Fès"
    assert rank(office)[0] == 2


def test_profile_config_rejects_string_instead_of_array(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCOVERY_PROFILES", '"AB"')
    with pytest.raises(ValueError, match="discovery_profiles_must_be_json_array"):
        Config.load(tmp_path)


def make_pdf(stream):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    content, offsets = b"%PDF-1.4\n", []
    for n, obj in enumerate(objects, 1):
        offsets.append(len(content))
        content += str(n).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref = len(content)
    content += (
        b"xref\n0 6\n0000000000 65535 f \n"
        + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
        + b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref).encode()
        + b"\n%%EOF\n"
    )
    return content


def test_two_column_pdf_preserves_contiguous_experience(tmp_path):
    """Le CV de production a révélé un entrelacement du bandeau et des missions."""
    from linkedin_discovery.connectors import read_cv

    stream = (
        b"BT /F1 10 Tf 40 740 Td (A left column of personal notes) Tj "
        b"0 -12 Td (that flows over several lines) Tj "
        b"0 -12 Td (without interrupting the experience.) Tj ET "
        b"BT /F1 10 Tf 300 740 Td (Develop workflows for OCR and) Tj "
        b"0 -12 Td (structured document extraction.) Tj "
        b"0 -12 Td (Use GraphRAG for search.) Tj ET"
    )
    path = tmp_path / "two-columns.pdf"
    path.write_bytes(make_pdf(stream))
    _, text = read_cv(path)
    assert "Develop workflows for OCR and structured document extraction." in " ".join(text.split())


def test_rejected_responses_stay_private_with_specific_failure_code(pilot):
    def invalid_quote(offer, cv, prompt):
        r = result(offer)
        r["competence_cv"] = "invented private fragment"
        return r

    pilot.codex.qualify = invalid_quote
    cycle = create(pilot)
    pilot.run(cycle)
    responses = pilot.store.db.execute("SELECT response FROM attempt_responses").fetchall()
    assert len(responses) == 3
    assert all("invented private fragment" in r["response"] for r in responses)
    errors = pilot.store.db.execute("SELECT error FROM attempts").fetchall()
    assert all(r["error"] == "skill_quote_not_in_cv" for r in errors)
    assert "invented private fragment" not in str(
        [dict(r) for r in pilot.store.db.execute("SELECT * FROM events")]
    )


def test_prompt_snapshot_preserves_all_lines(tmp_path):
    from linkedin_discovery.prompts import qualification_prompt

    path = tmp_path / "qualification.txt"
    path.write_text("Missions uniquement.\nCitations exactes du CV extrait.\n")
    assert (
        qualification_prompt(prompt_file=path)
        == "Missions uniquement.\nCitations exactes du CV extrait."
    )


def test_dashboard_params_resume_and_human_selection(pilot):
    from linkedin_discovery.dashboard import snapshot
    from linkedin_discovery.launch import Search

    search = Search(["GraphRAG"], "Rabat", "r86400", 12)
    ident = pilot.create(cv_data=(b"%PDF-test", CV), search=search)
    calls = []
    start = pilot.apify.start

    def capture(profile, limit, **filters):
        calls.append((profile, limit, filters))
        return start(profile, limit)

    pilot.apify.start = capture
    state = pilot.run(ident)
    pilot.run(ident)
    assert calls == [("GraphRAG", 12, {"location": "Rabat", "period": "r86400"})]
    listing = snapshot(pilot.config, "", "")
    assert len(listing["offers"]) == 1
    key = listing["offers"][0]["key"]
    assert snapshot(pilot.config, ident, key)["detail"]["observations"][0]["raw"] == raw()
    pilot.store.review(state["report_id"], 1, "écarter")
    assert snapshot(pilot.config, "", "")["offers"] == []
    assert "detail" not in snapshot(pilot.config, "", key)


@pytest.mark.parametrize("field", ["mission_citee", "competence_cv"])
def test_certain_verdict_requires_visible_evidence(field):
    offer = normalize(raw())
    with pytest.raises(ValueError, match="evidence_missing"):
        checked_result({**result(offer), field: " \n\t "}, offer, CV)


@pytest.mark.skipif(not os.environ.get("TEST_CV_POSTGRES_DSN"), reason="PostgreSQL isolé requis")
def test_two_cycle_documents_postgres(tmp_path, monkeypatch):
    import psycopg

    from linkedin_discovery.documents import cycle_cv, freeze_cv
    from linkedin_discovery.model import digest

    dsn = os.environ["TEST_CV_POSTGRES_DSN"]
    cv = tmp_path / "reference.pdf"
    config = Config(root=tmp_path, cv=cv, postgres_dsn=dsn)
    pilot = Pilot(config, codex=FakeCodex())
    originals = {}
    for label in ("2024 Atelier GraphRAG", "2025 Bureau Python"):
        pdf = make_pdf(f"BT /F1 10 Tf 40 740 Td ({label}) Tj ET".encode())
        cv.write_bytes(pdf)
        cycle = pilot.create()
        markdown = f"# Curriculum vitæ\n\n{label}"
        originals[cycle] = pdf, markdown
        assert pilot.store.cycle(cycle)["cv_text"] == markdown

    first, second = originals
    reference = originals[first]
    assert cycle_cv(dsn, second) == originals[second]
    cv.unlink()
    (pilot.store.data / "snapshots" / (digest(reference[0]) + ".pdf")).unlink()
    assert cycle_cv(dsn, first) == reference
    pilot.ingest(first, "test", raw())
    pilot.qualify({"cycle_id": first})
    assert len(pilot.codex.calls) == 1
    assert pilot.codex.calls[0][1] == reference[1]
    report = pilot.report({"cycle_id": first})
    pilot.store.close()
    pilot = Pilot(config)

    def unexpected_extraction(pdf):
        pytest.fail("extraction répétée")

    monkeypatch.setattr("linkedin_discovery.documents.extract_text", unexpected_extraction)
    replay = pilot.replay(report["report_id"])
    assert cycle_cv(dsn, replay) == reference
    with pytest.raises(ValueError, match="cycle_cv_changed"):
        freeze_cv(dsn, first, originals[second][0], None, "injected")
    assert cycle_cv(dsn, first) == reference
    with psycopg.connect(dsn) as db:
        row = db.execute(
            "SELECT sha256, provenance FROM documents.cv_versions WHERE pdf = %s", (reference[0],)
        ).fetchone()
        assert row == (digest(reference[0]), "DISCOVERY_CV/reference.pdf")
        assert not db.execute(
            "SELECT has_table_privilege(current_user, 'documents.cv_versions', 'UPDATE')"
        ).fetchone()[0]
    pilot.store.close()


@pytest.mark.skipif(not os.getenv("TEST_CV_POSTGRES_DSN"), reason="recette PostgreSQL isolée")
def test_postgres_qualification_review_replay(tmp_path):
    import psycopg

    class MixedCodex(FakeCodex):
        def qualify(self, offer, cv, prompt):
            if offer["description"] == "Panne":
                raise ConnectorError("codex_unavailable")
            if offer["description"] == "Mission imprécise":
                return {
                    **result(offer),
                    "incertitude": True,
                    "competence_cv": "",
                    "mission_citee": "",
                }
            return result(offer)

    dsn = os.environ["TEST_CV_POSTGRES_DSN"]
    config = Config(root=tmp_path, postgres_dsn=dsn, collect_seconds=0)
    apify = FakeApify([[raw("661"), raw("662", "Mission imprécise"), raw("663", "Panne")], [], []])
    pilot = Pilot(config, apify=apify, codex=MixedCodex())
    cycle = create(pilot)
    state = pilot.run(cycle)
    report = state["report_id"]
    original = Path(state["report_path"]).read_bytes()
    pilot.store.validate_report(report)
    pilot.store.validate_report(report)
    pilot.store.review(report, 1, "écarter", "Correction de recette")
    pilot.store.close()
    assert not (config.data / "discovery.sqlite3").exists()

    # Un autre worker retrouve le rapport et les preuves depuis PostgreSQL.
    pilot = Pilot(Config(root=tmp_path / "reprise", postgres_dsn=dsn), codex=MixedCodex())
    items = {r["offer"]["description"]: r for r in pilot.store.items(cycle)}
    corrected = items["Construire des solutions IA avec GraphRAG."]
    assert corrected["result"]["verdict"] == "retenir"
    assert corrected["effective_verdict"] == "écarter"
    assert items["Mission imprécise"]["result"]["incertitude"]
    assert items["Mission imprécise"]["human_verdict"] is None
    failed = items["Panne"]
    assert failed["status"] == "error" and failed["effective_verdict"] is None
    with psycopg.connect(dsn) as db:
        assert db.execute(
            "SELECT count(*) FROM discovery.attempts WHERE qualification_id=%s",
            (failed["qualification_id"],),
        ).fetchone() == (3,)
        assert db.execute(
            "SELECT count(*) FROM discovery.pilot_validations WHERE report_id=%s", (report,)
        ).fetchone() == (1,)
        assert db.execute(
            "SELECT count(*) FROM discovery.reviews WHERE report_id=%s", (report,)
        ).fetchone() == (1,)
        snapshot = json.loads(
            db.execute("SELECT snapshot FROM discovery.reports WHERE id=%s", (report,)).fetchone()[
                0
            ]
        )
        assert len(snapshot["selected"]) == 2
        assert all(i["human_verdict"] is None for i in snapshot["selected"])
    replay = pilot.replay(report, prompt="Rejeu de recette")
    pilot.run(replay)
    comparisons = pilot.compare(report, replay)["comparisons"]
    assert [r["agrees"] for r in comparisons] == [False, None]
    assert Path(state["report_path"]).read_bytes() == original
    pilot.store.close()


@pytest.mark.skipif(not os.getenv("TEST_CV_POSTGRES_DSN"), reason="recette PostgreSQL isolée")
def test_postgres_checkpoint_resume(tmp_path, monkeypatch):
    import asyncio

    import psycopg

    from linkedin_discovery import studio

    dsn = os.environ["TEST_CV_POSTGRES_DSN"]
    config = Config(root=tmp_path / "premier", postgres_dsn=dsn, collect_seconds=0)
    pilot = Pilot(config, apify=FakeApify(), codex=FakeCodex())
    cycle = create(pilot)
    report = pilot.report
    ids = []

    def crash_after_report(state):
        ids.append(report(state)["report_id"])
        raise RuntimeError("coupure_de_recette")

    monkeypatch.setattr(pilot, "report", crash_after_report)
    with pytest.raises(RuntimeError, match="coupure_de_recette"):
        pilot.run(cycle)
    assert len(pilot.apify.started) == 3 and len(pilot.codex.calls) == 1
    original = (config.data / "reports" / (ids[0] + ".html")).read_bytes()
    pilot.store.close()

    config = Config(root=tmp_path / "second", postgres_dsn=dsn)
    assert not config.data.exists()

    class NoNetwork:
        def __getattr__(self, name):
            pytest.fail(f"Connecteur rappelé en reprise : {name}")

    def reopened(config):
        return Pilot(config, apify=NoNetwork(), codex=NoNetwork())

    monkeypatch.setattr(studio.Config, "load", lambda: config)
    monkeypatch.setattr(studio, "DiscoveryService", reopened)

    async def resume():
        async with studio.make_graph() as graph:
            return await graph.ainvoke({"cycle_id": cycle})

    resumed = asyncio.run(resume())
    assert resumed["report_id"] == ids[0]
    assert Path(resumed["report_path"]).read_bytes() == original
    assert Path(resumed["report_path"]).is_relative_to(config.data)
    pilot = reopened(Config(root=tmp_path / "troisieme", postgres_dsn=dsn))
    final = pilot.run(cycle)
    assert final["report_id"] == resumed["report_id"]
    assert Path(final["report_path"]).read_bytes() == original
    assert Path(final["report_path"]).is_relative_to(pilot.store.data)
    # Cycle préexistant sans fil technique : réutilise les faits du métier.
    legacy = pilot.create(cv_data=(b"%PDF-history", CV), prompt="missions only")
    pilot.ingest(legacy, "fixture", raw("12121"))
    pilot.codex = FakeCodex()
    pilot.qualify({"cycle_id": legacy})
    pilot.store.execute("UPDATE cycles SET status='collected' WHERE id=?", (legacy,))
    legacy_report = pilot.report({"cycle_id": legacy})["report_id"]
    pilot.codex = NoNetwork()
    assert pilot.run(legacy)["report_id"] == legacy_report
    pilot.store.close()

    with psycopg.connect(dsn) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM runtime_g1.checkpoints WHERE thread_id=%s", (cycle,)
            ).fetchone()[0]
            >= 4
        )
        assert db.execute(
            "SELECT count(*) FROM discovery.reports WHERE cycle_id=%s", (cycle,)
        ).fetchone() == (1,)
        assert db.execute(
            """SELECT count(*) FROM discovery.attempts a JOIN discovery.cycle_items i
                ON i.qualification_id=a.qualification_id WHERE i.cycle_id=%s""",
            (cycle,),
        ).fetchone() == (1,)
        assert not db.execute(
            "SELECT has_schema_privilege(current_user, 'runtime_g1', 'CREATE')"
        ).fetchone()[0]
        assert not db.execute(
            "SELECT has_schema_privilege('linkedin_applications', 'runtime_g1', 'USAGE')"
        ).fetchone()[0]
