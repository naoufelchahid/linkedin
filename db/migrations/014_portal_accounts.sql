CREATE TABLE applications.confirmed_addresses (
    candidate text NOT NULL, mode text NOT NULL CHECK (mode IN ('recipe','production')),
    email text NOT NULL, confirmed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (candidate, mode)
);

CREATE TABLE applications.portal_accounts (
    id uuid PRIMARY KEY,
    candidate text NOT NULL, mode text NOT NULL,
    provider text NOT NULL, employer_space text NOT NULL,
    login_email text NOT NULL, encrypted_password bytea NOT NULL,
    status text NOT NULL DEFAULT 'creation_en_cours'
        CHECK (status IN ('creation_en_cours', 'confirmation_en_attente', 'actif')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (candidate, mode, provider, employer_space),
    FOREIGN KEY (candidate,mode) REFERENCES applications.confirmed_addresses
);

GRANT SELECT, INSERT ON applications.confirmed_addresses, applications.portal_accounts TO linkedin_applications;
GRANT UPDATE (email,confirmed_at) ON applications.confirmed_addresses TO linkedin_applications;
GRANT UPDATE (status) ON applications.portal_accounts TO linkedin_applications;

CREATE TABLE applications.dossier_portal_accounts (
    dossier_id uuid NOT NULL REFERENCES applications.dossiers(id),
    account_id uuid NOT NULL REFERENCES applications.portal_accounts(id),
    PRIMARY KEY (dossier_id, account_id)
);
GRANT SELECT, INSERT ON applications.dossier_portal_accounts TO linkedin_applications;
