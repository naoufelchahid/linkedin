CREATE TABLE documents.cv_versions (
    sha256 text PRIMARY KEY,
    pdf bytea NOT NULL CHECK (substring(pdf FROM 1 FOR 4) = '%PDF'::bytea),
    markdown text NOT NULL CHECK (length(trim(markdown)) > 0),
    provenance text NOT NULL CHECK (length(trim(provenance)) > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (sha256 = encode(sha256(pdf), 'hex'))
);
CREATE TABLE discovery.cycle_cv (
    cycle_id text PRIMARY KEY,
    cv_sha256 text NOT NULL REFERENCES documents.cv_versions(sha256)
);
GRANT USAGE ON SCHEMA documents TO linkedin_discovery;
GRANT SELECT, INSERT ON documents.cv_versions, discovery.cycle_cv TO linkedin_discovery;
