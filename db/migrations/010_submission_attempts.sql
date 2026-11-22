CREATE TABLE applications.submission_attempts (
    id uuid PRIMARY KEY,
    dossier_id uuid NOT NULL REFERENCES applications.dossiers(id),
    generation bigint NOT NULL CHECK (generation > 0),
    version_id text NOT NULL REFERENCES discovery.versions(id),
    cv_sha256 text NOT NULL REFERENCES documents.cv_versions(sha256),
    letter_sha256 text,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    lease_until timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('transmitting','no_submission','confirmed')),
    outcome jsonb,
    UNIQUE (dossier_id, generation),
    UNIQUE (dossier_id, id)
);
CREATE UNIQUE INDEX submission_unresolved ON applications.submission_attempts(dossier_id)
    WHERE status IN ('transmitting','confirmed');
CREATE TABLE applications.submission_receipts (
    dossier_id uuid PRIMARY KEY,
    attempt_id uuid NOT NULL UNIQUE,
    observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    evidence jsonb NOT NULL,
    FOREIGN KEY (dossier_id, attempt_id) REFERENCES applications.submission_attempts(dossier_id, id)
);
GRANT SELECT, INSERT ON applications.submission_attempts, applications.submission_receipts TO linkedin_applications;
GRANT UPDATE (lease_until,status,outcome) ON applications.submission_attempts TO linkedin_applications;
