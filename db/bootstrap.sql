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
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'linkedin_selection') THEN
        CREATE ROLE linkedin_selection NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'linkedin_applications') THEN
        CREATE ROLE linkedin_applications NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'linkedin_web') THEN
        CREATE ROLE linkedin_web NOLOGIN;
    END IF;
END $$;
GRANT linkedin_selection TO linkedin_applications;
CREATE SCHEMA IF NOT EXISTS runtime_g2 AUTHORIZATION linkedin_migrator;
CREATE SCHEMA IF NOT EXISTS applications AUTHORIZATION linkedin_migrator;
CREATE SCHEMA IF NOT EXISTS discovery AUTHORIZATION linkedin_migrator;
CREATE SCHEMA IF NOT EXISTS documents AUTHORIZATION linkedin_migrator;
CREATE SCHEMA IF NOT EXISTS api AUTHORIZATION linkedin_migrator;
COMMIT;
