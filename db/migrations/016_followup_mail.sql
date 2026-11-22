CREATE TABLE applications.followup_reviews (
    sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dossier_id uuid NOT NULL REFERENCES applications.submission_receipts(dossier_id),
    question_id uuid NOT NULL UNIQUE,
    version text NOT NULL,
    draft jsonb NOT NULL,
    approved_at timestamptz,
    UNIQUE(dossier_id, question_id, version)
);
CREATE INDEX followup_latest_review ON applications.followup_reviews(dossier_id, sequence DESC);
CREATE TABLE applications.followup_sends (
    dossier_id uuid PRIMARY KEY,
    question_id uuid NOT NULL,
    version text NOT NULL,
    attempt_id uuid NOT NULL UNIQUE,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    receipt jsonb,
    FOREIGN KEY (dossier_id, question_id, version)
        REFERENCES applications.followup_reviews(dossier_id, question_id, version)
);
GRANT SELECT, INSERT ON applications.followup_reviews, applications.followup_sends TO linkedin_applications;
GRANT UPDATE (approved_at) ON applications.followup_reviews TO linkedin_applications;
GRANT UPDATE (receipt) ON applications.followup_sends TO linkedin_applications;
