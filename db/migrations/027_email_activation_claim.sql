ALTER TABLE applications.email_challenges
    ADD COLUMN activation_message_sha256 text UNIQUE;
GRANT UPDATE (activation_message_sha256) ON applications.email_challenges
    TO linkedin_applications;
