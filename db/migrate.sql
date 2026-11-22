\set ON_ERROR_STOP on
BEGIN;
SET LOCAL ROLE linkedin_migrator;
SELECT pg_advisory_xact_lock(1765839004);
CREATE TABLE IF NOT EXISTS discovery.schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 1) AS pending \gset
\if :pending
    \ir migrations/001_apify.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (1);
\endif
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 2) AS pending \gset
\if :pending
    \ir migrations/002_cycle_cv.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (2);
\endif
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 3) AS pending \gset
\if :pending
    \ir migrations/003_qualification.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (3);
\endif
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 4) AS pending \gset
\if :pending
    \ir migrations/004_retained.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (4);
\endif
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 5) AS pending \gset
\if :pending
    \ir migrations/005_application_lots.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (5);
\endif
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 9) AS pending \gset
\if :pending
    \ir migrations/009_dossier_letter.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (9);
\endif
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 10) AS pending \gset
\if :pending
    \ir migrations/010_submission_attempts.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (10);
\endif
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 12) AS pending \gset
\if :pending
    \ir migrations/012_submission_mandate.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (12);
\endif
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 13) AS pending \gset
\if :pending
    \ir migrations/013_candidate_answers.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (13);
\endif
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 14) AS pending \gset
\if :pending
    \ir migrations/014_portal_accounts.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (14);
\endif
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 15) AS pending \gset
\if :pending
    \ir migrations/015_email_challenges.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (15);
\endif
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 16) AS pending \gset
\if :pending
    \ir migrations/016_followup_mail.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (16);
\endif
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 17) AS pending \gset
\if :pending
    \ir migrations/017_portal_obstacles.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (17);
\endif
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 18) AS pending \gset
\if :pending
    \ir migrations/018_web_offers.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (18);
\endif
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 19) AS pending \gset
\if :pending
    \ir migrations/019_offer_detail.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (19);
\endif
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 21) AS pending \gset
\if :pending
    \ir migrations/021_restored_history.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (21);
\endif
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 25) AS pending \gset
\if :pending
    \ir migrations/025_web_operational_status.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (25);
\endif
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 26) AS pending \gset
\if :pending
    \ir migrations/026_runtime_g1.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (26);
\endif
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 105) AS pending \gset
\if :pending
    \ir migrations/105_frozen_cycle_text.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (105);
\endif
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 110) AS pending \gset
\if :pending
    \ir migrations/110_runtime_g2.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (110);
\endif
COMMIT;
