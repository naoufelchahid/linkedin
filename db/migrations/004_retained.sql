-- Existing PostgreSQL versions were normalized at ingestion.
ALTER TABLE discovery.versions ADD COLUMN canonical_url text;
UPDATE discovery.versions SET canonical_url = NULLIF(content->>'url','');
ALTER TABLE discovery.versions
    ADD COLUMN identity text GENERATED ALWAYS AS
        (coalesce(nullif(canonical_url,''), offer_key)) STORED,
    ADD COLUMN created_at timestamptz;
UPDATE discovery.versions v SET created_at = (
    SELECT min(o.observed_at) FROM discovery.occurrences o WHERE o.version_id = v.id
);
ALTER TABLE discovery.versions ALTER COLUMN created_at SET DEFAULT clock_timestamp();

CREATE INDEX reviews_latest_version ON discovery.reviews(version_id, id DESC);
CREATE VIEW api.offres_retenues_v1 AS
WITH latest AS (
    SELECT DISTINCT ON (i.cycle_id, v.identity)
        i.cycle_id, v.identity, v.id AS version_id, v.canonical_url, v.content,
        q.result::jsonb AS result, c.cv_hash AS cv_sha256
    FROM discovery.cycle_items i
    JOIN discovery.versions v ON v.id = i.version_id
    JOIN discovery.qualifications q ON q.id = i.qualification_id
    JOIN discovery.cycles c ON c.id = i.cycle_id
    ORDER BY i.cycle_id, v.identity, v.created_at DESC NULLS LAST, v.id
), judged AS (
    SELECT l.*, coalesce(h.verdict, l.result->>'verdict') AS verdict
    FROM latest l
    LEFT JOIN LATERAL (
        SELECT r.verdict FROM discovery.reviews r
        WHERE r.version_id = l.version_id ORDER BY r.id DESC LIMIT 1
    ) h ON true
)
SELECT cycle_id, identity, version_id, canonical_url, content, verdict,
       (result->>'incertitude')::boolean AS incertitude, cv_sha256
FROM judged WHERE verdict = 'retenir';

GRANT USAGE ON SCHEMA api TO linkedin_selection;
GRANT SELECT ON api.offres_retenues_v1 TO linkedin_selection;
