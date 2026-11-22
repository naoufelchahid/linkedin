-- Ne projeter aucun contenu des prompts, des réponses ou des messages du candidat.
CREATE VIEW api.suivi_offres_v1 AS
SELECT DISTINCT ON (d.identity) d.identity, d.version_id AS dossier_version,
       obstacle.kind AS last_obstacle, a.generation, a.id AS attempt_id, r.observed_at AS receipt_at,
       encode(sha256(convert_to(r.evidence::text,'UTF8')),'hex') AS receipt_sha256,
       substring(r.evidence->>'url' FROM '^https://([a-zA-Z0-9.-]+)(?:[/?#]|$)') AS receipt_host,
       greatest(d.created_at,a.started_at,r.observed_at) AS activity,
       CASE WHEN r.attempt_id IS NOT NULL THEN 'dépôt confirmé'
            WHEN a.status='transmitting' THEN 'dépôt à vérifier'
            WHEN a.outcome->>'status'='blocked' THEN 'bloquée'
            WHEN a.outcome->>'status'='waiting' THEN 'en attente'
            ELSE 'dossier ouvert' END AS state
FROM applications.dossiers d
LEFT JOIN LATERAL (
    SELECT t.* FROM applications.submission_attempts t WHERE t.dossier_id=d.id
    ORDER BY t.generation DESC LIMIT 1
) a ON true
LEFT JOIN LATERAL (
    SELECT CASE t.outcome#>>'{question,kind}'
        WHEN 'registration' THEN 'Inscription en attente'
        WHEN 'challenge' THEN 'Vérification humaine demandée'
        WHEN 'question' THEN 'Réponse du candidat attendue'
        ELSE 'Formulaire bloqué' END AS kind
    FROM applications.submission_attempts t
    WHERE t.dossier_id=d.id AND t.outcome->>'status' IN ('blocked','waiting')
    ORDER BY t.generation DESC LIMIT 1
) obstacle ON true
LEFT JOIN applications.submission_receipts r ON r.dossier_id=d.id
WHERE d.mode='production'
ORDER BY d.identity, (r.attempt_id IS NOT NULL) DESC,
         greatest(d.created_at,a.started_at,r.observed_at) DESC, d.id;

ALTER VIEW api.offres_web_v1 RENAME TO observations_web_v1;
REVOKE SELECT ON api.observations_web_v1 FROM linkedin_web;
CREATE VIEW api.offres_web_v1 AS
SELECT o.identity,o.offer_id,o.cycle_id,o.version_id,o.canonical_url,o.title,o.company,
       o.location,o.contract_type,o.observed_at,o.verdict,coalesce(s.state,o.state) AS state,
       greatest(s.activity,o.activity) AS activity
FROM api.observations_web_v1 o LEFT JOIN api.suivi_offres_v1 s USING(identity);

CREATE VIEW api.sources_offres_v1 AS
SELECT encode(sha256(convert_to(v.identity,'UTF8')),'hex') AS offer_id,
       v.id AS version_id,o.cycle_id,o.profile,o.observed_at,o.raw_hash,
       v.content->>'work_mode' AS work_mode,v.content->>'posted_at' AS posted_at,
       coalesce(nullif(o.missions,''),v.content->>'description') AS missions,
       coalesce(o.raw->>'descriptionText',o.raw->>'description',o.raw->>'descriptionHtml',
                o.raw->>'jobDescription',v.content->>'description') AS source_text,
       o.raw->>'experienceLevel' AS experience,o.raw->>'salary' AS salary,
       o.raw->>'sector' AS sector,o.raw->>'workType' AS work_type
FROM discovery.occurrences o JOIN discovery.versions v ON v.id=o.version_id;

CREATE VIEW api.chronologie_offres_v1 AS
WITH events(identity,at,kind,version_id,context) AS (
    SELECT v.identity, o.observed_at, 'collecte', v.id, o.cycle_id
    FROM discovery.occurrences o JOIN discovery.versions v ON v.id=o.version_id
    UNION ALL
    SELECT v.identity,coalesce(a.finished_at,a.started_at)::timestamptz,
           'qualification',v.id,a.status FROM discovery.attempts a
    JOIN discovery.qualifications q ON q.id=a.qualification_id
    JOIN discovery.versions v ON v.id=q.version_id
    UNION ALL
    SELECT v.identity,r.created_at::timestamptz,'revue',v.id,r.verdict FROM discovery.reviews r
    JOIN discovery.versions v ON v.id=r.version_id
    UNION ALL
    SELECT d.identity,l.created_at,'lot',d.version_id,l.id::text
    FROM applications.lots l JOIN applications.lot_dossiers ld ON ld.lot_id=l.id
    JOIN applications.dossiers d ON d.id=ld.dossier_id WHERE d.mode='production'
    UNION ALL
    SELECT d.identity,a.started_at,'tentative',a.version_id,a.generation::text
    FROM applications.submission_attempts a JOIN applications.dossiers d ON d.id=a.dossier_id
    WHERE d.mode='production'
    UNION ALL
    SELECT d.identity,r.observed_at,'confirmation',d.version_id,r.attempt_id::text
    FROM applications.submission_receipts r JOIN applications.dossiers d ON d.id=r.dossier_id
    WHERE d.mode='production'
)
SELECT encode(sha256(convert_to(identity,'UTF8')),'hex') AS offer_id,at,kind,version_id,context
FROM events;
GRANT SELECT ON api.offres_web_v1,api.suivi_offres_v1,api.sources_offres_v1,
                api.chronologie_offres_v1 TO linkedin_web;
