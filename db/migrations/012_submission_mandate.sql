-- Une tentative historique garde son absence de provenance explicite.
ALTER TABLE applications.submission_attempts
    ADD COLUMN mandate_version text,
    ADD COLUMN mandate_sha256 text,
    ADD COLUMN mandate_text text,
    ADD CONSTRAINT submission_mandate_integrity CHECK (
        num_nonnulls(mandate_version, mandate_sha256, mandate_text) = 0 OR
        (num_nonnulls(mandate_version, mandate_sha256, mandate_text) = 3 AND
         mandate_sha256 = encode(sha256(convert_to(mandate_text, 'UTF8')), 'hex'))
    );
