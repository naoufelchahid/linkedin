CREATE TABLE applications.candidate_questions (
    id uuid PRIMARY KEY,
    dossier_id uuid NOT NULL REFERENCES applications.dossiers(id),
    prompt text NOT NULL,
    context jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE applications.candidate_answers (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    question_id uuid NOT NULL REFERENCES applications.candidate_questions(id),
    value text NOT NULL,
    source text NOT NULL DEFAULT 'telegram',
    source_message_id bigint NOT NULL,
    button_message_id bigint,
    received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    scope text CHECK (scope IN ('dossier', 'global')),
    decided_at timestamptz,
    CHECK ((scope IS NULL) = (decided_at IS NULL)),
    UNIQUE (question_id, source_message_id)
);
CREATE UNIQUE INDEX candidate_answer_confirmed ON applications.candidate_answers(question_id)
    WHERE scope IS NOT NULL;
CREATE TABLE applications.attempt_answers (
    attempt_id uuid NOT NULL REFERENCES applications.submission_attempts(id),
    answer_id bigint NOT NULL REFERENCES applications.candidate_answers(id),
    PRIMARY KEY(attempt_id, answer_id)
);
GRANT SELECT, INSERT ON applications.candidate_questions, applications.candidate_answers,
    applications.attempt_answers TO linkedin_applications;
GRANT UPDATE (scope, decided_at, button_message_id) ON applications.candidate_answers TO linkedin_applications;
GRANT USAGE ON SEQUENCE applications.candidate_answers_id_seq TO linkedin_applications;
