-- Exécuter avec le compte d'administration de la base.
\set ON_ERROR_STOP on
BEGIN;
SELECT pg_advisory_xact_lock(1765839004);
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'linkedin_migrator') THEN
        CREATE ROLE linkedin_migrator NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'linkedin_discovery') THEN
        CREATE ROLE linkedin_discovery NOLOGIN;
    END IF;
END $$;
CREATE SCHEMA IF NOT EXISTS discovery AUTHORIZATION linkedin_migrator;
CREATE SCHEMA IF NOT EXISTS documents AUTHORIZATION linkedin_migrator;
COMMIT;
