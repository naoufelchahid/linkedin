CREATE TABLE applications.portal_obstacles (
    attempt_id uuid PRIMARY KEY REFERENCES applications.submission_attempts(id),
    portal text,
    stage text NOT NULL,
    signal text NOT NULL,
    observation text NOT NULL,
    cause text NOT NULL,
    transmission_attempted boolean NOT NULL,
    observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_checked_at timestamptz,
    correction_result text NOT NULL DEFAULT 'en_attente'
        CHECK (correction_result IN ('en_attente','non_verifie','etat_verifie','recu_verifie'))
);
GRANT SELECT,INSERT ON applications.portal_obstacles TO linkedin_applications;
GRANT UPDATE (last_checked_at,correction_result) ON applications.portal_obstacles TO linkedin_applications;
