"""Relie les opérations applicatives aux trois écrans sans exposer leur contenu."""

import hashlib
import os
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
from linkedin_applications.postgres_queue import PostgresQueue
from linkedin_discovery.dashboard import app
from starlette.testclient import TestClient
from web_metrics import check_counts

PRIVATE = "temoin-confidentiel"


def seed(db):
    db.execute("""
        INSERT INTO discovery.versions(id,offer_key,content)
        SELECT 'rev-'||n,'cle-rev-'||n,jsonb_build_object('title','Offre revue '||n,'company','Revue')
        FROM generate_series(1,6) n;
        INSERT INTO discovery.occurrences(cycle_id,profile,raw_hash,raw,version_id)
        SELECT 'A','revue',id,'{}',id FROM discovery.versions WHERE id LIKE 'rev-%';
        INSERT INTO discovery.qualifications(id,version_id,cv_hash,prompt_hash,status,result)
        SELECT v.id,v.id,c.sha256,'p','done','{"verdict":"retenir"}'
        FROM discovery.versions v,documents.cv_versions c WHERE v.id LIKE 'rev-%';
        INSERT INTO discovery.cycle_items SELECT 'A',id,id FROM discovery.versions WHERE id LIKE 'rev-%';
        INSERT INTO applications.dossiers(id,candidate,identity,mode,cycle_id,version_id,canonical_url,
                                          content,cv_sha256,uncertain)
        SELECT gen_random_uuid(),'revue',v.identity,'production','A',v.id,
               'https://example.invalid','{}',c.sha256,false
        FROM discovery.versions v,documents.cv_versions c WHERE v.id LIKE 'rev-%';
        INSERT INTO applications.legacy_holds SELECT id,'temoin-confidentiel','production','submitted'
        FROM applications.dossiers WHERE version_id='rev-1';
        INSERT INTO applications.confirmed_addresses(candidate,mode,email)
        VALUES ('revue','production','temoin-confidentiel@example.invalid');
        INSERT INTO applications.portal_accounts(id,candidate,mode,provider,employer_space,login_email,encrypted_password)
        VALUES(gen_random_uuid(),'revue','production','test','recette','temoin-confidentiel@example.invalid','temoin-confidentiel');
        INSERT INTO applications.dossier_portal_accounts
        SELECT d.id,a.id FROM applications.dossiers d,applications.portal_accounts a
        WHERE d.version_id='rev-2' AND a.candidate='revue';
        INSERT INTO applications.email_challenges(dossier_id,account_id,started_at,browser_tab)
        SELECT dossier_id,account_id,now(),1 FROM applications.dossier_portal_accounts;
        INSERT INTO applications.submission_attempts(id,dossier_id,generation,version_id,cv_sha256,lease_until,status)
        SELECT gen_random_uuid(),id,1,version_id,cv_sha256,now(),
               CASE version_id WHEN 'rev-3' THEN 'no_submission' WHEN 'rev-4' THEN 'transmitting'
                    ELSE 'confirmed' END
        FROM applications.dossiers WHERE version_id IN ('rev-3','rev-4','rev-5');
        INSERT INTO applications.submission_receipts(dossier_id,attempt_id,evidence)
        SELECT dossier_id,id,'{"private":"temoin-confidentiel"}' FROM applications.submission_attempts WHERE version_id='rev-5';
        INSERT INTO applications.followup_reviews(dossier_id,question_id,version,draft)
        SELECT id,gen_random_uuid(),'revue','{"subject":"temoin-confidentiel"}' FROM applications.dossiers
        WHERE version_id='rev-5';
    """)


def assert_state(client, num, state, *labels):
    path = "/dashboard/offres/" + hashlib.sha256(f"cle-rev-{num}".encode()).hexdigest()
    page = client.get(path)
    listing = client.get(
        "/dashboard/offres", params={"entreprise": "Revue", "etat": state}
    )
    assert page.status_code == listing.status_code == 200
    assert path in listing.text and state.capitalize() in page.text
    assert all(label in page.text for label in labels)
    assert PRIVATE not in page.text and PRIVATE not in listing.text


def main(work):
    queue = PostgresQueue(work, "options='-c role=linkedin_applications'", "revue")
    with psycopg.connect() as db:
        seed(db)
        db.execute("""INSERT INTO applications.dossiers(id,candidate,identity,mode,cycle_id,version_id,canonical_url,content,cv_sha256,uncertain)
            SELECT gen_random_uuid(),candidate,identity,'recipe',cycle_id,version_id,canonical_url,content,cv_sha256,uncertain
            FROM applications.dossiers WHERE version_id='rev-5' AND mode='production'""")
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations/025_web_operational_status.sql"
        )
        db.execute(migration.read_text())
        attempts = dict(
            db.execute("""SELECT version_id,id FROM applications.submission_attempts
                                     WHERE version_id IN ('rev-3','rev-4')""").fetchall()
        )
        question_dossier = db.execute(
            "SELECT id FROM applications.dossiers WHERE version_id='rev-6'"
        ).fetchone()[0]
        db.execute("SET LOCAL ROLE linkedin_web")
        assert (
            db.execute("""SELECT mode,state,receipt_reference IS NOT NULL,in_pipe
            FROM api.suivi_candidatures_v1 WHERE identity='cle-rev-5' ORDER BY mode""").fetchall()
            == [
                ("production", "suivi à approuver", True, False),
                ("recipe", "dossier ouvert", False, True),
            ]
        )
        assert (
            db.execute("""SELECT count(*),count(DISTINCT dossier_id),count(activity)
            FROM api.suivi_candidatures_v1 WHERE identity LIKE 'cle-rev-%'""").fetchone()
            == (7, 7, 7)
        )
        assert db.execute(
            "SELECT has_table_privilege(current_user,'api.suivi_candidatures_v1','UPDATE')"
        ).fetchone() == (False,)
        for table in (
            "legacy_holds",
            "portal_obstacles",
            "email_challenges",
            "followup_reviews",
            "followup_sends",
            "candidate_answers",
        ):
            assert not db.execute(
                """SELECT has_table_privilege(current_user,oid,'SELECT')
                                      FROM pg_class WHERE relname=%s""",
                (table,),
            ).fetchone()[0]
    for ver, signal, transmitted in (
        ("rev-3", "permission_refusee", False),
        ("rev-4", "http_403_apres_validation", True),
    ):
        queue.submissions.obstacle(
            attempts[ver],
            {
                "stage": "validation",
                "signal": signal,
                "portal": "example.invalid",
                "cause": PRIVATE,
                "observation": PRIVATE,
                "transmission_attempted": transmitted,
            },
        )
    question = str(uuid4())
    queue.candidate_answers.open(
        {"dossier": question_dossier, "question": {"id": question, "text": PRIVATE}}
    )
    os.environ["DASHBOARD_POSTGRES_DSN"] = "user=web_recette"
    with TestClient(app, base_url="http://localhost") as client:
        assert_state(client, 1, "reprise suspendue", "Rapprochement requis")
        assert_state(client, 2, "confirmation en attente", "Confirmation demandée")
        assert_state(client, 3, "bloquée", "Permission locale refusée")
        assert_state(client, 4, "dépôt à vérifier", "HTTP 403 après validation")
        assert_state(client, 5, "suivi à approuver", "Reçu de dépôt")
        assert_state(client, 6, "réponse en attente")
        assert PRIVATE not in check_counts(
            client, {"entreprise": "Revue"}, [6, 6, 1, 2, 6, 0, 0, 0, 1, 2, 1, 2, 3]
        )
        with psycopg.connect() as db:
            db.execute("""
                UPDATE applications.email_challenges SET matched_message_sha256='temoin-confidentiel',confirmed_at=now()
                WHERE dossier_id IN (SELECT id FROM applications.dossiers WHERE version_id='rev-2');
                UPDATE applications.followup_reviews SET approved_at=now() WHERE version='revue';
            """)
        queue.submissions.obstacle_checked(attempts["rev-3"], True)
        answer = queue.candidate_answers.stage(question, PRIVATE, 3)
        queue.candidate_answers.bind_buttons(answer, 4)
        queue.candidate_answers.confirm(question, answer, 4, "once")
        assert_state(client, 2, "dossier ouvert", "Confirmation reçue")
        assert_state(client, 3, "dossier ouvert", "État vérifié")
        assert_state(client, 6, "dossier ouvert")
        assert_state(client, 5, "suivi approuvé", "Brouillon approuvé")
        with psycopg.connect() as db:
            db.execute("""INSERT INTO applications.followup_sends(dossier_id,question_id,version,attempt_id)
                SELECT dossier_id,question_id,version,gen_random_uuid() FROM applications.followup_reviews WHERE version='revue'""")
        assert_state(client, 5, "suivi à vérifier", "Reçu de dépôt")
        with psycopg.connect() as db:
            db.execute("""UPDATE applications.followup_sends SET receipt='{"private":"temoin-confidentiel"}'
                          WHERE version='revue'""")
        assert_state(client, 5, "suivi envoyé", "Reçu de dépôt")
        check_counts(
            client, {"entreprise": "Revue"}, [6, 6, 1, 2, 6, 0, 0, 0, 1, 2, 0, 3, 3]
        )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
