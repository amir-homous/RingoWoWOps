CREATE TABLE IF NOT EXISTS guilds (
    guild_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    game_version TEXT NOT NULL,
    region TEXT NOT NULL,
    realm TEXT NOT NULL,
    normalized_realm TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    UNIQUE(game_version, region, normalized_realm, normalized_name)
);

CREATE TABLE IF NOT EXISTS guild_members (
    member_id TEXT PRIMARY KEY,
    guild_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    normalized_display_name TEXT NOT NULL,
    discord_user_id TEXT,
    membership_status TEXT NOT NULL DEFAULT 'active',
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(guild_id, normalized_display_name),
    UNIQUE(guild_id, discord_user_id),
    FOREIGN KEY(guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS guild_characters (
    external_character_key TEXT PRIMARY KEY,
    guild_id TEXT NOT NULL,
    member_id TEXT NOT NULL,
    game_version TEXT NOT NULL,
    region TEXT NOT NULL,
    realm TEXT NOT NULL,
    normalized_realm TEXT NOT NULL,
    character_name TEXT NOT NULL,
    normalized_character_name TEXT NOT NULL,
    class TEXT,
    primary_role TEXT,
    main_alt TEXT NOT NULL DEFAULT 'unspecified' CHECK(main_alt IN ('main','alt','unspecified')),
    character_status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(game_version, region, normalized_realm, normalized_character_name),
    FOREIGN KEY(guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE,
    FOREIGN KEY(member_id) REFERENCES guild_members(member_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS roster_import_rejections (
    rejection_id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    raw_record TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raid_events (
    event_key TEXT PRIMARY KEY,
    external_source TEXT NOT NULL,
    external_event_id TEXT NOT NULL,
    title TEXT NOT NULL,
    scheduled_at TEXT,
    instance TEXT,
    game_version TEXT NOT NULL,
    region TEXT NOT NULL,
    realm TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(external_source, external_event_id)
);

CREATE TABLE IF NOT EXISTS raid_event_reports (
    event_key TEXT NOT NULL,
    report_code TEXT NOT NULL,
    linked_at TEXT NOT NULL,
    PRIMARY KEY(event_key, report_code),
    FOREIGN KEY(event_key) REFERENCES raid_events(event_key) ON DELETE CASCADE,
    FOREIGN KEY(report_code) REFERENCES wcl_reports(report_code) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_guild_characters_member ON guild_characters(member_id);
CREATE INDEX IF NOT EXISTS idx_raid_event_reports_report ON raid_event_reports(report_code);
