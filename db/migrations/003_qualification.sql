SET LOCAL search_path TO discovery, pg_catalog;
CREATE TABLE cycles(
 id TEXT PRIMARY KEY, created_at TEXT NOT NULL, cv_hash TEXT NOT NULL,
 cv_text TEXT NOT NULL, prompt_hash TEXT NOT NULL, prompt TEXT NOT NULL,
 settings TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'created');
CREATE TABLE runs(
 cycle_id TEXT REFERENCES cycles(id), profile TEXT, run_id TEXT,
 status TEXT NOT NULL, dataset_id TEXT, error TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(cycle_id, profile));
CREATE TABLE qualifications(
 id TEXT PRIMARY KEY, version_id TEXT REFERENCES versions(id), cv_hash TEXT,
 prompt_hash TEXT, status TEXT NOT NULL, result TEXT, error TEXT NOT NULL DEFAULT '',
 UNIQUE(version_id, cv_hash, prompt_hash));
CREATE TABLE attempts(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, qualification_id TEXT REFERENCES qualifications(id),
 number INTEGER, status TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
 started_at TEXT NOT NULL, finished_at TEXT, UNIQUE(qualification_id, number));
CREATE TABLE attempt_responses(
 qualification_id TEXT REFERENCES qualifications(id), number INTEGER,
 response TEXT NOT NULL, PRIMARY KEY(qualification_id,number));
CREATE TABLE cycle_items(
 cycle_id TEXT REFERENCES cycles(id), version_id TEXT REFERENCES versions(id),
 qualification_id TEXT REFERENCES qualifications(id), PRIMARY KEY(cycle_id,version_id));
CREATE TABLE reports(
 id TEXT PRIMARY KEY, cycle_id TEXT REFERENCES cycles(id), created_at TEXT,
 snapshot TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL);
CREATE TABLE review_items(
 report_id TEXT REFERENCES reports(id), number INTEGER, version_id TEXT,
 qualification_id TEXT, PRIMARY KEY(report_id,number));
CREATE TABLE reviews(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, report_id TEXT, number INTEGER, version_id TEXT,
 verdict TEXT NOT NULL CHECK(verdict IN ('retenir','écarter')), note TEXT,
 created_at TEXT NOT NULL,
 FOREIGN KEY(report_id,number) REFERENCES review_items(report_id,number));
CREATE TABLE events(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, cycle_id TEXT, step TEXT NOT NULL, status TEXT NOT NULL,
 duration REAL NOT NULL, created_at TEXT NOT NULL, technical_id TEXT NOT NULL DEFAULT '');
CREATE TABLE pilot_validations(
 report_id TEXT PRIMARY KEY REFERENCES reports(id), created_at TEXT NOT NULL);
GRANT SELECT, INSERT ON cycles, runs, qualifications, attempts, attempt_responses,
 cycle_items, reports, review_items, reviews, events, pilot_validations TO linkedin_discovery;
GRANT UPDATE ON cycles, runs, qualifications, attempts, cycle_items, attempt_responses TO linkedin_discovery;
GRANT DELETE ON cycle_items TO linkedin_discovery;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA discovery TO linkedin_discovery;
