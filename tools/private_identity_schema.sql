ALTER TABLE raid_helper_signups ADD COLUMN discord_user_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_raid_helper_signups_discord_hash
ON raid_helper_signups(discord_user_hash);
