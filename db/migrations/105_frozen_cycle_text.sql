ALTER TABLE discovery.cycle_cv ADD COLUMN frozen_text text;
UPDATE discovery.cycle_cv b
SET frozen_text = c.cv_text
FROM discovery.cycles c WHERE c.id=b.cycle_id AND c.cv_hash=b.cv_sha256;
UPDATE discovery.cycle_cv b
SET frozen_text = v.markdown
FROM documents.cv_versions v WHERE b.cv_sha256=v.sha256 AND b.frozen_text IS NULL;

INSERT INTO discovery.cycle_cv(cycle_id,cv_sha256,frozen_text)
SELECT c.id,c.cv_hash,c.cv_text FROM discovery.cycles c
JOIN documents.cv_versions v ON v.sha256=c.cv_hash
ON CONFLICT (cycle_id) DO NOTHING;

-- Les lots antérieurs peuvent référencer directement un CV sans ligne de liaison.
CREATE VIEW api.cycle_documents_v1 AS
SELECT coalesce(b.cycle_id,c.id) AS cycle_id, v.sha256, v.pdf,
       coalesce(b.frozen_text,c.cv_text,v.markdown) AS markdown
FROM discovery.cycle_cv b FULL JOIN discovery.cycles c ON c.id=b.cycle_id
JOIN documents.cv_versions v ON v.sha256=coalesce(b.cv_sha256,c.cv_hash);
GRANT USAGE ON SCHEMA api TO linkedin_discovery;
GRANT SELECT ON api.cycle_documents_v1 TO linkedin_discovery, linkedin_applications;
