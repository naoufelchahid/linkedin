CREATE TABLE discovery.versions (
    id text PRIMARY KEY,
    offer_key text NOT NULL,
    content jsonb NOT NULL
);
CREATE TABLE discovery.occurrences (
    cycle_id text NOT NULL,
    profile text NOT NULL,
    raw_hash text NOT NULL,
    raw jsonb NOT NULL CHECK (jsonb_typeof(raw) = 'object'),
    version_id text REFERENCES discovery.versions(id),
    error text,
    observed_at timestamptz NOT NULL DEFAULT now(),
    title text,
    contract_type text,
    company text,
    location text,
    canonical_url text,
    missions text,
    PRIMARY KEY (cycle_id, profile, raw_hash),
    CHECK ((version_id IS NULL) = (error IS NOT NULL))
);
GRANT USAGE ON SCHEMA discovery TO linkedin_discovery;
GRANT SELECT, INSERT ON discovery.versions, discovery.occurrences TO linkedin_discovery;
