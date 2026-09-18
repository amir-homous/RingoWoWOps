CREATE TABLE IF NOT EXISTS wcl_import_batches (
    id TEXT PRIMARY KEY,
    report_code TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    archive_path TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE(report_code, source_sha256)
);

CREATE TABLE IF NOT EXISTS wcl_reports (
    report_code TEXT PRIMARY KEY,
    title TEXT,
    owner_name TEXT,
    start_time INTEGER NOT NULL,
    end_time INTEGER NOT NULL,
    game_version TEXT NOT NULL,
    region TEXT NOT NULL,
    realm TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    last_import_batch_id TEXT NOT NULL,
    FOREIGN KEY(last_import_batch_id) REFERENCES wcl_import_batches(id)
);

CREATE TABLE IF NOT EXISTS wcl_fights (
    report_code TEXT NOT NULL,
    fight_id INTEGER NOT NULL,
    name TEXT,
    start_time INTEGER NOT NULL,
    end_time INTEGER NOT NULL,
    PRIMARY KEY(report_code, fight_id),
    FOREIGN KEY(report_code) REFERENCES wcl_reports(report_code) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS wcl_characters (
    external_character_key TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    game_version TEXT NOT NULL,
    region TEXT NOT NULL,
    realm TEXT NOT NULL,
    normalized_realm TEXT NOT NULL,
    is_guild_member INTEGER NOT NULL DEFAULT 0 CHECK(is_guild_member IN (0,1)),
    UNIQUE(game_version, region, normalized_realm, normalized_name)
);

CREATE TABLE IF NOT EXISTS wcl_report_participants (
    report_code TEXT NOT NULL,
    external_character_key TEXT NOT NULL,
    wcl_actor_id INTEGER NOT NULL,
    PRIMARY KEY(report_code, external_character_key),
    UNIQUE(report_code, wcl_actor_id),
    FOREIGN KEY(report_code) REFERENCES wcl_reports(report_code) ON DELETE CASCADE,
    FOREIGN KEY(external_character_key) REFERENCES wcl_characters(external_character_key)
);

CREATE TABLE IF NOT EXISTS wcl_fight_attendance (
    report_code TEXT NOT NULL,
    fight_id INTEGER NOT NULL,
    external_character_key TEXT NOT NULL,
    PRIMARY KEY(report_code, fight_id, external_character_key),
    FOREIGN KEY(report_code, fight_id) REFERENCES wcl_fights(report_code, fight_id) ON DELETE CASCADE,
    FOREIGN KEY(report_code, external_character_key) REFERENCES wcl_report_participants(report_code, external_character_key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_wcl_fights_time ON wcl_fights(report_code, start_time);
CREATE INDEX IF NOT EXISTS idx_wcl_attendance_character ON wcl_fight_attendance(external_character_key, report_code);
