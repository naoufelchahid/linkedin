-- Les anciens threads mélangeaient parfois les modes. Leur reprise nécessite
-- un rapprochement explicite avec le checkpoint d'origine.
CREATE TABLE applications.legacy_holds (
    dossier_id uuid PRIMARY KEY REFERENCES applications.dossiers(id),
    original_thread text NOT NULL,
    original_mode text,
    original_status text NOT NULL,
    CHECK (length(original_thread) > 0)
);
GRANT SELECT (dossier_id) ON applications.legacy_holds TO linkedin_applications;

CREATE TABLE applications.legacy_history (
    kind text NOT NULL, source_key text NOT NULL, payload jsonb NOT NULL,
    PRIMARY KEY (kind,source_key)
);
CREATE TABLE applications.legacy_files (
    relative_path text PRIMARY KEY,
    content bytea NOT NULL,
    sha256 text NOT NULL CHECK (sha256 = encode(sha256(content),'hex'))
);
