-- Schéma final des migrations 0–9 de langgraph-checkpoint-postgres 3.2.1.
-- Les migrations sont appliquées avec le rôle propriétaire, avant le démarrage des workers.
CREATE TABLE runtime_g1.checkpoint_migrations (v integer PRIMARY KEY);
INSERT INTO runtime_g1.checkpoint_migrations SELECT generate_series(0,9);
CREATE TABLE runtime_g1.checkpoints (
    thread_id text NOT NULL, checkpoint_ns text NOT NULL DEFAULT '', checkpoint_id text NOT NULL,
    parent_checkpoint_id text, type text, checkpoint jsonb NOT NULL, metadata jsonb NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);
CREATE TABLE runtime_g1.checkpoint_blobs (
    thread_id text NOT NULL, checkpoint_ns text NOT NULL DEFAULT '', channel text NOT NULL,
    version text NOT NULL, type text NOT NULL, blob bytea,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);
CREATE TABLE runtime_g1.checkpoint_writes (
    thread_id text NOT NULL, checkpoint_ns text NOT NULL DEFAULT '', checkpoint_id text NOT NULL,
    task_id text NOT NULL, idx integer NOT NULL, channel text NOT NULL, type text, blob bytea NOT NULL,
    task_path text NOT NULL DEFAULT '',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);
CREATE INDEX checkpoints_thread_id_idx ON runtime_g1.checkpoints(thread_id);
CREATE INDEX checkpoint_blobs_thread_id_idx ON runtime_g1.checkpoint_blobs(thread_id);
CREATE INDEX checkpoint_writes_thread_id_idx ON runtime_g1.checkpoint_writes(thread_id);
GRANT USAGE ON SCHEMA runtime_g1 TO linkedin_discovery;
GRANT SELECT,INSERT ON runtime_g1.checkpoints,runtime_g1.checkpoint_blobs,runtime_g1.checkpoint_writes TO linkedin_discovery;
GRANT UPDATE (checkpoint, metadata) ON runtime_g1.checkpoints TO linkedin_discovery;
GRANT UPDATE (channel, type, blob) ON runtime_g1.checkpoint_writes TO linkedin_discovery;
