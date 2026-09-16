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

WoW runtime lifecycle verification remains manual.

## Phase 2 — Unified gold ledger

Planned, not implemented. Add explicit manual income, expense, gift, and transfer entries; reconcile them against observed balance changes; never infer that raw change is profit.

## Phase 3 — Structured activities and runs

Planned. Add extensible farm/dungeon/run records and link them to ledger entries and sessions.

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
