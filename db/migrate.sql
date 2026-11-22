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
COMMIT;
