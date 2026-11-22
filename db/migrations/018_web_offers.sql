-- Une observation par cycle et version, y compris avant la qualification.
CREATE VIEW api.offres_web_v1 AS
WITH observations AS (
    SELECT DISTINCT ON (o.cycle_id, o.version_id)
        o.cycle_id, o.version_id, o.observed_at, o.contract_type
    FROM discovery.occurrences o
    WHERE o.version_id IS NOT NULL
    ORDER BY o.cycle_id, o.version_id, o.observed_at DESC, o.profile, o.raw_hash
)
SELECT v.identity, encode(sha256(convert_to(v.identity, 'UTF8')), 'hex') AS offer_id,
       o.cycle_id, v.id AS version_id, v.canonical_url,
       v.content->>'title' AS title, v.content->>'company' AS company,
       v.content->>'location' AS location, o.contract_type, o.observed_at,
       coalesce(h.verdict, q.result::jsonb->>'verdict',
           CASE WHEN q.status IN ('error','data_problem') THEN 'erreur'
                ELSE 'en attente' END) AS verdict,
       CASE WHEN d.created_at IS NULL THEN 'sans dossier' ELSE 'dossier ouvert' END AS state,
       greatest(o.observed_at, d.created_at, h.created_at::timestamptz) AS activity
FROM observations o
JOIN discovery.versions v ON v.id = o.version_id
LEFT JOIN discovery.cycle_items i ON (i.cycle_id, i.version_id) = (o.cycle_id, o.version_id)
LEFT JOIN discovery.qualifications q ON q.id = i.qualification_id
LEFT JOIN LATERAL (
    SELECT r.verdict, r.created_at FROM discovery.reviews r
    WHERE r.version_id = v.id ORDER BY r.id DESC LIMIT 1
) h ON true
LEFT JOIN LATERAL (
    SELECT max(created_at) AS created_at FROM applications.dossiers
    WHERE mode = 'production' AND identity = v.identity
) d ON true;

GRANT USAGE ON SCHEMA api TO linkedin_web;
GRANT SELECT ON api.offres_web_v1 TO linkedin_web;
