CREATE TABLE IF NOT EXISTS raid_helper_import_batches (
    batch_id TEXT PRIMARY KEY,
    event_key TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    archive_path TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE(event_key, source_sha256),
    FOREIGN KEY(event_key) REFERENCES raid_events(event_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS raid_helper_signups (
    signup_key TEXT PRIMARY KEY,
    event_key TEXT NOT NULL,
    external_signup_id TEXT,
    position INTEGER,
    display_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    discord_user_id TEXT,
    signup_status TEXT NOT NULL,
    class_name TEXT,
    role_name TEXT,
    spec_name TEXT,
    notes TEXT,
    signup_at TEXT,
    resolved_member_id TEXT,
    resolved_character_key TEXT,
    resolution_method TEXT,
    import_batch_id TEXT NOT NULL,
    raw_record TEXT NOT NULL,
    UNIQUE(event_key, external_signup_id),
    FOREIGN KEY(event_key) REFERENCES raid_events(event_key) ON DELETE CASCADE,
    FOREIGN KEY(resolved_member_id) REFERENCES guild_members(member_id) ON DELETE SET NULL,
    FOREIGN KEY(resolved_character_key) REFERENCES guild_characters(external_character_key) ON DELETE SET NULL,
    FOREIGN KEY(import_batch_id) REFERENCES raid_helper_import_batches(batch_id)
);

CREATE INDEX IF NOT EXISTS idx_raid_helper_signups_event ON raid_helper_signups(event_key);
CREATE INDEX IF NOT EXISTS idx_raid_helper_signups_member ON raid_helper_signups(resolved_member_id);
CREATE INDEX IF NOT EXISTS idx_raid_helper_signups_character ON raid_helper_signups(resolved_character_key);
