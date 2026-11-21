PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS cycles(
 id TEXT PRIMARY KEY, created_at TEXT NOT NULL, cv_hash TEXT NOT NULL,
 cv_text TEXT NOT NULL, prompt_hash TEXT NOT NULL, prompt TEXT NOT NULL,
 settings TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'created');
CREATE TABLE IF NOT EXISTS runs(
 cycle_id TEXT REFERENCES cycles(id), profile TEXT, run_id TEXT,
 status TEXT NOT NULL, dataset_id TEXT, error TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(cycle_id, profile));
CREATE TABLE IF NOT EXISTS occurrences(
 cycle_id TEXT REFERENCES cycles(id), profile TEXT, raw_hash TEXT,
 raw TEXT NOT NULL, version_id TEXT, error TEXT NOT NULL DEFAULT '', observed_at TEXT NOT NULL,
 PRIMARY KEY(cycle_id, profile, raw_hash));
CREATE TABLE IF NOT EXISTS versions(
 id TEXT PRIMARY KEY, offer_key TEXT NOT NULL, content_hash TEXT NOT NULL,
 content TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS qualifications(
 id TEXT PRIMARY KEY, version_id TEXT REFERENCES versions(id), cv_hash TEXT,
 prompt_hash TEXT, status TEXT NOT NULL, result TEXT, error TEXT NOT NULL DEFAULT '',
 UNIQUE(version_id, cv_hash, prompt_hash));
CREATE TABLE IF NOT EXISTS attempts(
 id INTEGER PRIMARY KEY, qualification_id TEXT REFERENCES qualifications(id),
 number INTEGER, status TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
 started_at TEXT NOT NULL, finished_at TEXT, UNIQUE(qualification_id, number));
CREATE TABLE IF NOT EXISTS attempt_responses(
 qualification_id TEXT REFERENCES qualifications(id), number INTEGER,
 response TEXT NOT NULL, PRIMARY KEY(qualification_id,number));
CREATE TABLE IF NOT EXISTS cycle_items(
 cycle_id TEXT REFERENCES cycles(id), version_id TEXT REFERENCES versions(id),
 qualification_id TEXT REFERENCES qualifications(id), PRIMARY KEY(cycle_id,version_id));
CREATE TABLE IF NOT EXISTS reports(
 id TEXT PRIMARY KEY, cycle_id TEXT REFERENCES cycles(id), created_at TEXT,
 snapshot TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS review_items(
 report_id TEXT REFERENCES reports(id), number INTEGER, version_id TEXT,
 qualification_id TEXT, PRIMARY KEY(report_id,number));
CREATE TABLE IF NOT EXISTS reviews(
 id INTEGER PRIMARY KEY, report_id TEXT, number INTEGER, version_id TEXT,
 verdict TEXT NOT NULL CHECK(verdict IN ('retenir','écarter')), note TEXT,
 created_at TEXT NOT NULL,
 FOREIGN KEY(report_id,number) REFERENCES review_items(report_id,number));
CREATE TABLE IF NOT EXISTS events(
 id INTEGER PRIMARY KEY, cycle_id TEXT, step TEXT NOT NULL, status TEXT NOT NULL,
 duration REAL NOT NULL, created_at TEXT NOT NULL, technical_id TEXT NOT NULL DEFAULT '');
