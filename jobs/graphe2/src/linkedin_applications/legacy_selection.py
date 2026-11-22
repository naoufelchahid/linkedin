"""Contrat historique de lecture des sélections SQLite."""

from .urls import offer_url

RETAINED = """
WITH ranked AS (
 SELECT v.id,v.content,v.offer_key,q.result,c.id cycle,c.created_at,c.cv_hash,c.cv_text,
 coalesce(nullif(offer_url(json_extract(v.content,'$.url')),''),v.offer_key) identity,
 (SELECT verdict FROM reviews WHERE version_id=v.id ORDER BY id DESC LIMIT 1) human,
 row_number() OVER (PARTITION BY coalesce(nullif(offer_url(json_extract(v.content,'$.url')),''),v.offer_key)
 ORDER BY c.created_at DESC,v.created_at DESC,v.id) pos
 FROM cycle_items i JOIN versions v ON v.id=i.version_id
 JOIN qualifications q ON q.id=i.qualification_id JOIN cycles c ON c.id=i.cycle_id
 WHERE (?='' OR c.id=?)
), accepted AS (
 SELECT *,coalesce(human,json_extract(result,'$.verdict')) verdict FROM ranked
)
SELECT a.*, (SELECT min(b.created_at) FROM accepted b WHERE b.identity=a.identity
 AND b.verdict='retenir') retained_since FROM accepted a
 WHERE pos=1 AND verdict='retenir' ORDER BY retained_since DESC
"""


def retained_rows(db, cycle):
    db.create_function("offer_url", 1, offer_url, deterministic=True)
    return db.execute(RETAINED, (cycle, cycle))
