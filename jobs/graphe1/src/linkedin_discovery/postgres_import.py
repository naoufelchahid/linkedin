"""Import transactionnel d'un dataset Apify exporté en JSON."""

import argparse
import json
from pathlib import Path

import psycopg

from .model import digest, dump, normalize, offer_url, plain


def import_collection(connection, cycle_id, profile, dataset_json):
    if not cycle_id or not profile:
        raise ValueError("invalid_collection")
    inserted = 0
    with connection.transaction(), connection.cursor() as cursor:
        # PostgreSQL décode le JSON source avant Python pour préserver aussi les
        # décimales Apify que float ne peut pas représenter exactement.
        items = connection.execute(
            "SELECT value::text FROM jsonb_array_elements(%s::jsonb)", (dataset_json,)
        )
        for (payload,) in items:
            raw = json.loads(payload)
            if not isinstance(raw, dict):
                raise ValueError("item_not_object")
            try:
                offer = normalize(raw)
            except (TypeError, ValueError):
                offer = {}
            _, count = insert_offer(cursor, cycle_id, profile, raw, payload, offer)
            inserted += count
    return inserted


def insert_offer(cursor, cycle_id, profile, raw, payload, offer):
    version_id = None
    if offer:
        content = dump(offer)
        version_id = digest(content)
        cursor.execute(
            """INSERT INTO discovery.versions (id, offer_key, content, canonical_url)
               VALUES (%s, %s, %s::jsonb, %s) ON CONFLICT (id) DO NOTHING""",
            (version_id, offer["key"], content, offer_url(offer.get("url")) or None),
        )
    contract = raw.get("contractType") or raw.get("employmentType") or raw.get("jobType")
    cursor.execute(
        """INSERT INTO discovery.occurrences (
               cycle_id, profile, raw_hash, raw, version_id, error, title,
               contract_type, company, location, canonical_url, missions
           ) VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (cycle_id, profile, raw_hash) DO NOTHING""",
        (
            cycle_id,
            profile,
            digest(payload),
            payload,
            version_id,
            None if offer else "announcement_unusable",
            offer.get("title") or None,
            plain(contract) or None,
            offer.get("company") or None,
            offer.get("location") or None,
            offer.get("url") or None,
            offer.get("description") or None,
        ),
    )
    return version_id, cursor.rowcount


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    dataset_json = args.dataset.read_text(encoding="utf-8")
    # libpq résout le compte de service et les secrets via PG* ou .pgpass.
    with psycopg.connect() as connection:
        count = import_collection(connection, args.cycle, args.profile, dataset_json)
    print(json.dumps({"occurrences_inserted": count}))


if __name__ == "__main__":
    main()
