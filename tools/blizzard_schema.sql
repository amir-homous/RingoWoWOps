CREATE TABLE IF NOT EXISTS blizzard_profile_import_batches (
    batch_id TEXT PRIMARY KEY,
    external_character_key TEXT NOT NULL,
    source_namespace TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('imported','unchanged','unsupported','missing','failed')),
    archive_path TEXT,
    sanitized_error_json TEXT,
    UNIQUE(external_character_key, source_namespace, source_sha256)
);

CREATE TABLE IF NOT EXISTS blizzard_character_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    external_character_key TEXT NOT NULL,
    source_namespace TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    character_name TEXT NOT NULL,
    realm TEXT NOT NULL,
    region TEXT NOT NULL,
    game_version TEXT NOT NULL,
    level INTEGER,
    race_name TEXT,
    class_name TEXT,
    faction_name TEXT,
    active_spec_name TEXT,
    professions_json TEXT,
    average_item_level REAL,
    equipped_item_level REAL,
    profile_last_modified TEXT,
    source_url TEXT NOT NULL,
    import_batch_id TEXT NOT NULL,
    UNIQUE(external_character_key, source_namespace, fetched_at, source_sha256),
    FOREIGN KEY(external_character_key) REFERENCES guild_characters(external_character_key) ON DELETE RESTRICT,
    FOREIGN KEY(import_batch_id) REFERENCES blizzard_profile_import_batches(batch_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS blizzard_equipment_snapshots (
    snapshot_id TEXT NOT NULL,
    slot_type TEXT NOT NULL,
    item_id INTEGER,
    item_name TEXT,
    item_level INTEGER,
    item_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, slot_type),
    FOREIGN KEY(snapshot_id) REFERENCES blizzard_character_snapshots(snapshot_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_blizzard_snapshots_character_time
ON blizzard_character_snapshots(external_character_key, fetched_at);

CREATE VIEW IF NOT EXISTS blizzard_character_sync_summary AS
SELECT gc.external_character_key,
       s.level AS level,
       s.average_item_level AS latest_avg_item_level,
       s.active_spec_name AS current_spec,
       s.source_url AS blizzard_profile,
       s.fetched_at AS gear_snapshot_at,
       b.fetched_at AS last_synced_at,
       CASE WHEN b.batch_id IS NULL THEN NULL ELSE 'Blizzard API' END AS sync_sources,
       b.status AS sync_status
FROM guild_characters gc
LEFT JOIN blizzard_character_snapshots s ON s.snapshot_id = (
    SELECT s2.snapshot_id FROM blizzard_character_snapshots s2
    WHERE s2.external_character_key=gc.external_character_key
    ORDER BY s2.fetched_at DESC, s2.snapshot_id DESC LIMIT 1
)
LEFT JOIN blizzard_profile_import_batches b ON b.batch_id = (
    SELECT b2.batch_id FROM blizzard_profile_import_batches b2
    WHERE b2.external_character_key=gc.external_character_key
    ORDER BY b2.fetched_at DESC, b2.batch_id DESC LIMIT 1
);
