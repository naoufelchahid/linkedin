-- Le rôle web reçoit des états dérivés. Ni les messages ni les secrets des comptes
-- ni les réponses du candidat ne font partie du contrat.
-- Les dossiers déjà migrés gardent leurs instants connus. Les prochains
-- brouillons et confirmations de suivi reçoivent la date de leur écriture.
ALTER TABLE applications.followup_reviews ADD COLUMN IF NOT EXISTS presented_at timestamptz;
ALTER TABLE applications.followup_reviews ALTER COLUMN presented_at SET DEFAULT clock_timestamp();
ALTER TABLE applications.followup_sends ADD COLUMN IF NOT EXISTS confirmed_at timestamptz;
CREATE OR REPLACE FUNCTION applications.date_followup_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.receipt IS NOT NULL AND NEW.confirmed_at IS NULL THEN
        NEW.confirmed_at := clock_timestamp();
    END IF;
    RETURN NEW;
END;
$$;
CREATE OR REPLACE TRIGGER date_followup_receipt BEFORE INSERT OR UPDATE OF receipt
ON applications.followup_sends FOR EACH ROW EXECUTE FUNCTION applications.date_followup_receipt();

CREATE OR REPLACE VIEW api.suivi_candidatures_v1 AS
WITH dossiers AS (
    SELECT d.identity,d.id,d.mode,d.cycle_id,d.version_id AS dossier_version,
           a.generation,a.id AS attempt_id,a.status AS attempt_status,
           a.outcome->>'status' AS outcome_status,
           r.observed_at AS receipt_at,r.attempt_id AS receipt_reference,
           encode(sha256(convert_to(r.evidence::text,'UTF8')),'hex') AS receipt_sha256,
           substring(r.evidence->>'url' FROM '^https://([a-zA-Z0-9.-]+)(?:[/?#]|$)') AS receipt_host,
           h.dossier_id IS NOT NULL AS held,h.original_status AS held_status,
           e.dossier_id IS NOT NULL AND e.confirmed_at IS NULL AS email_pending,
           e.confirmed_at IS NOT NULL AS email_confirmed,
           q.id IS NOT NULL AS has_question,q.decided_at IS NOT NULL AS has_answer,
           p.attempt_id=a.id AS current_obstacle,p.transmission_attempted,p.correction_result,
           CASE p.signal WHEN 'permission_refusee' THEN 'Permission locale refusée'
             WHEN 'session_expiree' THEN 'Session expirée'
             WHEN 'champ_indisponible' THEN 'Champ indisponible'
             WHEN 'piece_incomplete' THEN 'Pièce incomplète'
             WHEN 'limitation_debit' THEN 'Limitation de débit'
             WHEN 'verification_humaine' THEN 'Vérification humaine demandée'
             WHEN 'http_403_apres_validation' THEN 'HTTP 403 après validation'
             ELSE CASE WHEN p.attempt_id IS NOT NULL THEN 'Blocage de cause indéterminée' END
           END AS diagnosis, fallback.kind,
           CASE WHEN p.stage IN ('ouverture','connexion','formulaire','piece','validation','confirmation')
                THEN p.stage END AS obstacle_stage,
           p.observed_at AS obstacle_at,p.last_checked_at AS obstacle_checked_at,
           review.sequence AS review_id,review.approved_at,
           send.attempt_id AS send_id,send.receipt IS NOT NULL AS mail_sent,
           greatest(d.created_at,a.started_at,r.observed_at,e.started_at,e.confirmed_at,
                    p.observed_at,p.last_checked_at,q.created_at,q.decided_at,review.presented_at,review.approved_at,
                    send.started_at,send.confirmed_at) AS activity
    FROM applications.dossiers d
    LEFT JOIN LATERAL (
        SELECT t.* FROM applications.submission_attempts t WHERE t.dossier_id=d.id
        ORDER BY generation DESC LIMIT 1
    ) a ON true
    LEFT JOIN applications.submission_receipts r ON r.dossier_id=d.id
    LEFT JOIN applications.legacy_holds h ON h.dossier_id=d.id
    LEFT JOIN applications.email_challenges e ON e.dossier_id=d.id
    LEFT JOIN LATERAL (
        SELECT o.* FROM applications.submission_attempts t
        JOIN applications.portal_obstacles o ON o.attempt_id=t.id
        WHERE t.dossier_id=d.id ORDER BY t.generation DESC LIMIT 1
    ) p ON true
    LEFT JOIN LATERAL (
        SELECT CASE t.outcome#>>'{question,kind}'
            WHEN 'registration' THEN 'Inscription en attente'
            WHEN 'challenge' THEN 'Vérification humaine demandée'
            WHEN 'question' THEN 'Réponse du candidat attendue'
            ELSE 'Formulaire bloqué' END AS kind
        FROM applications.submission_attempts t WHERE t.dossier_id=d.id
        AND t.outcome->>'status' IN ('blocked','waiting') ORDER BY generation DESC LIMIT 1
    ) fallback ON true
    LEFT JOIN LATERAL (
        SELECT cq.id,cq.created_at,ca.decided_at FROM applications.candidate_questions cq
        LEFT JOIN applications.candidate_answers ca ON ca.question_id=cq.id AND ca.scope IS NOT NULL
        WHERE cq.dossier_id=d.id ORDER BY cq.created_at DESC,cq.id DESC LIMIT 1
    ) q ON true
    LEFT JOIN LATERAL (
        SELECT f.sequence,f.presented_at,f.approved_at FROM applications.followup_reviews f
        WHERE f.dossier_id=d.id ORDER BY f.sequence DESC LIMIT 1
    ) review ON true
    LEFT JOIN applications.followup_sends send ON send.dossier_id=d.id
), statuses AS (
    SELECT *, CASE
        WHEN held THEN 'reprise suspendue'
        WHEN receipt_at IS NOT NULL THEN CASE
            WHEN mail_sent THEN 'suivi envoyé'
            WHEN send_id IS NOT NULL THEN 'suivi à vérifier'
            WHEN approved_at IS NOT NULL THEN 'suivi approuvé'
            WHEN review_id IS NOT NULL THEN 'suivi à approuver'
            ELSE 'dépôt confirmé' END
        WHEN attempt_status='transmitting' OR (current_obstacle AND transmission_attempted
                  AND correction_result IN ('en_attente','non_verifie')) THEN 'dépôt à vérifier'
        WHEN current_obstacle AND correction_result IN ('en_attente','non_verifie') THEN 'bloquée'
        WHEN email_pending THEN 'confirmation en attente'
        WHEN has_question AND NOT has_answer THEN 'réponse en attente'
        WHEN outcome_status='blocked' AND NOT coalesce(current_obstacle,false) THEN 'bloquée'
        WHEN outcome_status='waiting' AND NOT email_confirmed AND NOT has_answer THEN 'en attente'
        ELSE 'dossier ouvert' END AS state
    FROM dossiers
)
SELECT id AS dossier_id,identity,mode,cycle_id,dossier_version,coalesce(diagnosis,kind) AS last_obstacle,
       generation,attempt_id,receipt_at,receipt_sha256,receipt_host,activity,state,
       CASE WHEN receipt_at IS NOT NULL THEN 'confirmé'
            WHEN state='dépôt à vérifier' OR (held AND (attempt_status='transmitting'
                 OR held_status IN ('submitted','submission_uncertain','submitting'))) THEN 'à vérifier'
            WHEN state='bloquée' THEN 'bloqué' ELSE 'autres' END AS deposit,
       correction_result,obstacle_stage,obstacle_at,obstacle_checked_at,receipt_reference,(mode<>'production' OR receipt_at IS NULL) AS in_pipe
FROM statuses;
GRANT SELECT ON api.suivi_candidatures_v1 TO linkedin_web;

CREATE OR REPLACE VIEW api.suivi_offres_v1 AS
SELECT DISTINCT ON (identity) identity,dossier_version,last_obstacle,generation,attempt_id,
       receipt_at,receipt_sha256,receipt_host,activity,state,deposit,correction_result,
       obstacle_stage,obstacle_at,obstacle_checked_at
FROM api.suivi_candidatures_v1 WHERE mode='production'
ORDER BY identity,(receipt_at IS NOT NULL) DESC,activity DESC,dossier_id;

-- Détails de suivi additionnels uniquement, avec libellés de portée fixe.
CREATE OR REPLACE VIEW api.evenements_operationnels_v1 AS
SELECT encode(sha256(convert_to(d.identity,'UTF8')),'hex') AS offer_id,
       ev.at,ev.kind,d.version_id,ev.context
FROM applications.dossiers d JOIN LATERAL (
    SELECT d.created_at AS at,'reprise' AS kind,'Rapprochement requis' AS context
    FROM applications.legacy_holds h WHERE h.dossier_id=d.id
    UNION ALL
    SELECT e.started_at,'compte','Confirmation demandée' FROM applications.email_challenges e WHERE e.dossier_id=d.id
    UNION ALL
    SELECT e.confirmed_at,'compte','Confirmation reçue' FROM applications.email_challenges e WHERE e.dossier_id=d.id AND e.confirmed_at IS NOT NULL
    UNION ALL
    SELECT o.observed_at,'obstacle','Diagnostic enregistré' FROM applications.portal_obstacles o
    JOIN applications.submission_attempts t ON t.id=o.attempt_id WHERE t.dossier_id=d.id
    UNION ALL
    SELECT o.last_checked_at,'obstacle',CASE o.correction_result WHEN 'non_verifie' THEN 'Correction non vérifiée'
        WHEN 'etat_verifie' THEN 'État vérifié' WHEN 'recu_verifie' THEN 'Reçu vérifié' END
    FROM applications.portal_obstacles o JOIN applications.submission_attempts t ON t.id=o.attempt_id
    WHERE t.dossier_id=d.id AND o.last_checked_at IS NOT NULL
    UNION ALL
    SELECT f.presented_at,'suivi','Brouillon présenté' FROM applications.followup_reviews f
    WHERE f.dossier_id=d.id AND f.presented_at IS NOT NULL
    UNION ALL
    SELECT f.approved_at,'suivi','Brouillon approuvé' FROM applications.followup_reviews f
    WHERE f.dossier_id=d.id AND f.approved_at IS NOT NULL
    UNION ALL
    SELECT f.started_at,'suivi','Tentative d’envoi' FROM applications.followup_sends f WHERE f.dossier_id=d.id
    UNION ALL
    SELECT f.confirmed_at,'suivi','Envoi confirmé' FROM applications.followup_sends f
    WHERE f.dossier_id=d.id AND f.confirmed_at IS NOT NULL
) ev ON true WHERE d.mode='production';
GRANT SELECT ON api.evenements_operationnels_v1 TO linkedin_web;
