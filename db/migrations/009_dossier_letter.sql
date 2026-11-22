CREATE TABLE documents.dossier_letters (
    dossier_id uuid PRIMARY KEY REFERENCES applications.dossiers(id),
    pdf bytea NOT NULL CHECK (substring(pdf FROM 1 FOR 4) = '%PDF'::bytea),
    sha256 text GENERATED ALWAYS AS (encode(sha256(pdf), 'hex')) STORED,
    created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON documents.dossier_letters TO linkedin_applications;
