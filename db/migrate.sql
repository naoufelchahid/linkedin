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
SELECT NOT EXISTS (SELECT FROM discovery.schema_migrations WHERE version = 18) AS pending \gset
\if :pending
    \ir migrations/018_web_offers.sql
    INSERT INTO discovery.schema_migrations (version) VALUES (18);
\endif
COMMIT;
