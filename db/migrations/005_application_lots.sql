CREATE TABLE applications.lots (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    candidate text NOT NULL, cycle_id text NOT NULL REFERENCES discovery.cycles(id),
    mode text NOT NULL CHECK (mode IN ('recipe','production')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(candidate, cycle_id, mode)
);
CREATE TABLE applications.dossiers (
    id uuid PRIMARY KEY,
    candidate text NOT NULL, identity text NOT NULL,
    mode text NOT NULL CHECK (mode IN ('recipe','production')),
    cycle_id text NOT NULL REFERENCES discovery.cycles(id),
    version_id text NOT NULL REFERENCES discovery.versions(id),
    canonical_url text NOT NULL, content jsonb NOT NULL,
    cv_sha256 text NOT NULL REFERENCES documents.cv_versions(sha256),
    uncertain boolean NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(candidate, identity, mode)
);
CREATE TABLE applications.lot_dossiers (
    lot_id bigint NOT NULL REFERENCES applications.lots(id),
    dossier_id uuid NOT NULL REFERENCES applications.dossiers(id),
    position integer NOT NULL, PRIMARY KEY(lot_id, dossier_id)
);
CREATE VIEW api.cycles_v1 AS SELECT id AS cycle_id FROM discovery.cycles;
GRANT SELECT ON api.cycles_v1 TO linkedin_applications;
GRANT USAGE ON SCHEMA applications, documents TO linkedin_applications;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA applications TO linkedin_applications;
GRANT SELECT (sha256, pdf, markdown) ON documents.cv_versions TO linkedin_applications;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA applications TO linkedin_applications;
