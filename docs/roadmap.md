# Roadmap

## Phase 0 — Audit and baseline

Completed. Repository, addon, raw schema, processed data, SQLite, report behavior, and documentation drift were audited without modifying historical raw data.

## Phase 1 — Data integrity and backward compatibility

Implemented:

- load-time addon migrations and synchronized versions
- stable source IDs/session associations for new records
- deterministic legacy compatibility IDs
- validation and provenance outputs
- transactional versioned SQLite migrations
- append-only idempotent imports and database backups
- source identity preservation without inferred merges
- path-stable CLI, schema-aware doctor, private upload manifest
- scoped calendar-day reporting and corrected balance terminology
- sanitized automated and end-to-end tests

Phase 1 runtime verification passed at v0.3.0, including migration and repeated import.

## Phase 2A - Minimal manual cash ledger

Implemented and user-validated in WoW at v0.4.0. Explicit income,
expense, gifts, one-sided transfers, strict money parsing, optional player-material
annotations, append-only voids, SQLite v4 import/conflict validation, and scoped
cash totals with conservative observation reconciliation. No profit/hour or new UI.
See [gold-ledger.md](gold-ledger.md) for acceptance and deployment checklist.

## Phase 2B - Ledger maintenance (deferred)

Manual/backdated CLI entries, legacy candidate review, transfer linking, controlled
adjustments and any ledger entry UI require a separate approved implementation.
Account-wide aggregation and inventory valuation remain deferred as well.

## Phase 3A - Farm Run Core and native dashboard

Implemented in source; v0.5.0 WoW validation pending. Stratholme preset, immutable
headers/events, validated lifecycle, reload/recovery, native Live Run / History /
Settings, schema v5 pipeline and scoped Raw gold change summaries. Existing ledger
and compact UI remain available. See [farm-dashboard.md](farm-dashboard.md).

## Phase 3B - Farm operations (deferred)

Buyer/payment/recruitment, loot/vendor/DE attribution, run-linked ledger economics,
AH/TSM, rates and specialized Botanica/Shadow Lab workflows are not implemented.
No automatic gameplay, reset, group or chat actions are introduced.

## Phase 4 — Professions and services

Planned. Track services, crafts, fees, tips, player materials, and customer-provided materials.

## Phase 5 — Dungeon and raid operations

Planned. Add instance runs, encounters, role/spec, attendance, wipes, loot references, and preparation data.

## Phase 6 — Character progression

Planned. Add reputations, professions, gear, lockouts, attunements, and phase-effective context.

## Phase 7 — Local dashboard

Planned after trustworthy query models exist.

## Phase 8 — Guild and roster operations

Planned as a logically separate guild-operation domain.

## Phase 9 — AI-assisted recommendations

Planned only after metrics have provenance, freshness, scope, and explainable assumptions.
