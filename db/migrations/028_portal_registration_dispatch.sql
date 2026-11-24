ALTER TABLE applications.portal_accounts
    ADD COLUMN registration_dispatched_at timestamptz;
GRANT UPDATE (registration_dispatched_at) ON applications.portal_accounts
    TO linkedin_applications;
