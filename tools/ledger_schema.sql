CREATE TABLE ledger_entries (
 record_id TEXT PRIMARY KEY NOT NULL,
 time INTEGER NOT NULL CHECK(typeof(time)='integer' AND time>=0),
 created_at INTEGER NOT NULL CHECK(typeof(created_at)='integer' AND created_at>=0),
 character_id INTEGER NOT NULL REFERENCES source_identities(id),
 character TEXT NOT NULL, realm TEXT NOT NULL,
 session_id TEXT,
 direction TEXT NOT NULL CHECK(direction IN ('in','out')),
 category TEXT NOT NULL,
 amount_copper INTEGER NOT NULL CHECK(typeof(amount_copper)='integer' AND amount_copper BETWEEN 1 AND 2147483647),
 amount_quality TEXT NOT NULL CHECK(amount_quality IN ('exact','estimated')),
 input_source TEXT NOT NULL CHECK(input_source='addon_command'),
 counterparty TEXT, note TEXT, activity TEXT,
 player_material_cost_copper INTEGER CHECK(player_material_cost_copper IS NULL OR (typeof(player_material_cost_copper)='integer' AND player_material_cost_copper BETWEEN 0 AND 2147483647)),
 material_cost_quality TEXT CHECK(material_cost_quality IN ('exact','estimated')),
 material_provision TEXT CHECK(material_provision IN ('customer','player','mixed','unknown')),
 schema_version INTEGER NOT NULL CHECK(schema_version=1),
 addon_schema_version INTEGER NOT NULL CHECK(addon_schema_version=4),
 source_file_sha256 TEXT NOT NULL, source_schema_version TEXT NOT NULL,
 source_record_index INTEGER NOT NULL, source_dataset TEXT NOT NULL,
 import_batch_id TEXT NOT NULL REFERENCES import_batches(id),
 logical_payload TEXT NOT NULL, raw_record TEXT NOT NULL,
 CHECK((direction='in' AND category IN ('service','craft','sale','activity','refund','other','gift','transfer')) OR
       (direction='out' AND category IN ('repair','training','supplies','materials','purchase','fees','other','gift','transfer'))),
 CHECK(category NOT IN ('gift','transfer') OR length(trim(counterparty))>0 AND counterparty IS NOT NULL),
 CHECK((player_material_cost_copper IS NULL AND material_cost_quality IS NULL) OR
       (player_material_cost_copper IS NOT NULL AND material_cost_quality IS NOT NULL)),
 CHECK(material_provision IS NULL OR material_provision!='customer' OR player_material_cost_copper IS NULL OR player_material_cost_copper=0),
 CHECK((player_material_cost_copper IS NULL AND material_provision IS NULL) OR
       (direction='in' AND category IN ('service','craft','sale','activity','other')))
);
CREATE TABLE ledger_voids (
 record_id TEXT PRIMARY KEY NOT NULL,
 entry_id TEXT NOT NULL UNIQUE REFERENCES ledger_entries(record_id),
 time INTEGER NOT NULL CHECK(typeof(time)='integer' AND time>=0),
 created_at INTEGER NOT NULL CHECK(typeof(created_at)='integer' AND created_at>=0),
 character_id INTEGER NOT NULL REFERENCES source_identities(id),
 character TEXT NOT NULL, realm TEXT NOT NULL,
 input_source TEXT NOT NULL CHECK(input_source='addon_command'), reason TEXT NOT NULL,
 schema_version INTEGER NOT NULL CHECK(schema_version=1),
 addon_schema_version INTEGER NOT NULL CHECK(addon_schema_version=4),
 source_file_sha256 TEXT NOT NULL, source_schema_version TEXT NOT NULL,
 source_record_index INTEGER NOT NULL, source_dataset TEXT NOT NULL,
 import_batch_id TEXT NOT NULL REFERENCES import_batches(id),
 logical_payload TEXT NOT NULL, raw_record TEXT NOT NULL
);
CREATE INDEX idx_ledger_scope_time ON ledger_entries(character_id,time);
CREATE INDEX idx_ledger_identity_time ON ledger_entries(character,realm,time);
CREATE INDEX idx_ledger_session ON ledger_entries(session_id);
CREATE INDEX idx_ledger_batch ON ledger_entries(import_batch_id);
CREATE INDEX idx_void_scope_time ON ledger_voids(character,realm,time);
