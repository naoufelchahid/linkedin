CREATE TABLE applications.email_challenges (
    dossier_id uuid PRIMARY KEY,
    account_id uuid NOT NULL,
    started_at timestamptz NOT NULL,
    browser_tab bigint NOT NULL CHECK (browser_tab > 0),
    matched_message_sha256 text UNIQUE,
    confirmed_at timestamptz,
    CHECK ((matched_message_sha256 IS NULL) = (confirmed_at IS NULL)),
    FOREIGN KEY (dossier_id, account_id)
      REFERENCES applications.dossier_portal_accounts(dossier_id,account_id)
);
GRANT SELECT, INSERT ON applications.email_challenges TO linkedin_applications;
GRANT UPDATE (matched_message_sha256,confirmed_at) ON applications.email_challenges TO linkedin_applications;
