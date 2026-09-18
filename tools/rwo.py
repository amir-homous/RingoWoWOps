import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from generate_daily_report import resolve_timezone
from import_to_sqlite import SCHEMA_VERSION
from data_model import DATASETS
import wcl
import roster
import raid_helper


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config.json"
REQUIRED_CONFIG = ("wow_path", "account")


def load_config(path: Path) -> dict:
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}. Copy config.example.json to config.json and edit it.")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    missing = [key for key in REQUIRED_CONFIG if not str(config.get(key, "")).strip()]
    if missing:
        raise ValueError(f"Missing required config key(s): {', '.join(missing)}")
    timezone_name = config.get("report_timezone", "UTC")
    resolve_timezone(timezone_name)
    return config


def project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def run(script: str, *args: str) -> None:
    command = [sys.executable, str(PROJECT_ROOT / "tools" / script), *args]
    print("+", " ".join(command))
    subprocess.run(command, check=True, cwd=PROJECT_ROOT)


def savedvariables_path(config: dict) -> Path:
    return (
        Path(config["wow_path"])
        / config.get("wow_flavor", "_anniversary_")
        / "WTF" / "Account" / config["account"] / "SavedVariables"
        / config.get("savedvariables_file", "RingoWoWOps.lua")
    )


def configured_paths(config: dict) -> dict[str, Path]:
    return {
        "raw": project_path(config.get("raw_output", "data/raw/RingoWoWOps.lua")),
        "processed": project_path(config.get("processed_dir", "data/processed")),
        "db": project_path(config.get("sqlite_db", "data/ringo_ops.sqlite")),
        "report": project_path(config.get("daily_report", "data/processed/daily_report.md")),
    }


def report_args(config: dict, paths: dict[str, Path]) -> list[str]:
    args = ["--db", str(paths["db"]), "--out", str(paths["report"]), "--timezone", config.get("report_timezone", "UTC")]
    for config_key, flag in (("report_end_date", "--end-date"), ("report_date", "--date"), ("report_character", "--character"), ("report_realm", "--realm")):
        if config.get(config_key):
            args.extend([flag, str(config[config_key])])
    return args


def update(config: dict) -> None:
    src, paths = savedvariables_path(config), configured_paths(config)
    if not src.exists():
        raise FileNotFoundError(f"SavedVariables file not found: {src}. Check wow_path, wow_flavor, and account.")
    paths["raw"].parent.mkdir(parents=True, exist_ok=True)
    paths["processed"].mkdir(parents=True, exist_ok=True)
    print(f"Copying trusted local SavedVariables {src} -> {paths['raw']}")
    shutil.copy2(src, paths["raw"])
    run("parse_savedvariables.py", str(paths["raw"]), "--out", str(paths["processed"]))
    run("import_to_sqlite.py", str(paths["processed"]), "--db", str(paths["db"]))
    run("generate_daily_report.py", *report_args(config, paths))
    manifest = paths["processed"] / "source_manifest.json"
    if manifest.exists():
        details = json.loads(manifest.read_text(encoding="utf-8"))
        print(f"Validation summary: {details.get('validation_counts', {})}")
        print(f"Record counts: {details.get('record_counts', {})}")
    print(f"Report ready: {paths['report']}")


def database_status(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    try:
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        migrations = conn.execute("SELECT count(*) FROM migration_history").fetchone()[0] if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='migration_history'").fetchone() else 0
        counts = {table: conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                  for table in ('ledger_entries','ledger_voids','farm_runs','farm_run_events')
                  if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone()}
        conn.close()
        if version > SCHEMA_VERSION:
            return f"ERROR - schema v{version} is newer than supported v{SCHEMA_VERSION}"
        state = 'OK' if version == SCHEMA_VERSION else 'MIGRATION REQUIRED'
        return f"{state} - schema v{version}, target v{SCHEMA_VERSION}, {migrations} migration record(s), domain counts {counts}"
    except sqlite3.Error as exc:
        return f"ERROR - {exc}"


def doctor(config: dict) -> None:
    paths = configured_paths(config)
    checks = [
        ("WoW path", Path(config["wow_path"])),
        ("SavedVariables", savedvariables_path(config)),
        ("Parser", PROJECT_ROOT / "tools/parse_savedvariables.py"),
        ("SQLite importer", PROJECT_ROOT / "tools/import_to_sqlite.py"),
        ("Daily report generator", PROJECT_ROOT / "tools/generate_daily_report.py"),
    ]
    ok = True
    for name, path in checks:
        exists = path.exists()
        print(f"{name}: {'OK' if exists else 'MISSING'} - {path}")
        ok &= exists
    db_state = database_status(paths["db"])
    print(f"Database: {db_state} - {paths['db']}")
    ok &= not db_state.startswith("ERROR")
    print(f"Report scope: calendar day, timezone={config.get('report_timezone', 'UTC')}, character={config.get('report_character', 'auto')}, realm={config.get('report_realm', 'auto')}")
    wcl_config = config.get("wcl")
    if not wcl_config:
        print("Warcraft Logs V1: not configured (optional)")
    else:
        env_name = str(wcl_config.get("api_key_env") or "WCL_V1_KEY")
        print(f"Warcraft Logs V1: {'available' if os.getenv(env_name) else 'missing'} (optional; credential environment variable {env_name})")
    if not ok:
        raise SystemExit(1)


def make_upload_zip(config: dict) -> None:
    print("PRIVACY WARNING: upload packages contain raw character history and may contain private notes.")
    update(config)
    paths = configured_paths(config)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / "data/upload"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"RingoWoWOps_upload_{stamp}.zip"
    candidates = [paths["raw"], paths["report"]] + [paths["processed"] / f"{name}.csv" for name in (*DATASETS, "validation_errors")] + [paths["processed"] / "source_manifest.json"]
    included = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in candidates:
            if file.exists():
                arcname = file.relative_to(PROJECT_ROOT).as_posix() if file.is_relative_to(PROJECT_ROOT) else file.name
                archive.write(file, arcname)
                is_raw_savedvariables = file.resolve() == paths["raw"].resolve()
                included.append({
                    "path": arcname,
                    "size": file.stat().st_size,
                    "privacy": "private_raw_savedvariables" if is_raw_savedvariables else "private_financial_history" if file.stem in ("ledger_entries", "ledger_voids") else "private_farm_history" if file.stem in ("farm_runs", "farm_run_events") else "may_contain_private_history",
                })
        upload_manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "privacy_warning": "The entry marked private_raw_savedvariables is the private raw WoW SavedVariables file. Other exports may contain private character history and notes.",
            "network_transmission": "none; this command creates a local ZIP only",
            "files": included,
        }
        archive.writestr("upload_manifest.json", json.dumps(upload_manifest, indent=2, sort_keys=True) + "\n")
    print(f"Upload package ready: {zip_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="RingoWoWOps local helper CLI")
    parser.add_argument("command", choices=["update", "doctor", "upload", "wcl-import", "roster-import", "raid-event-upsert", "raid-event-link-report", "attendance-report", "raid-helper-import", "raid-reconcile"])
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--report-code")
    parser.add_argument("--offline-json")
    parser.add_argument("--input")
    parser.add_argument("--source")
    parser.add_argument("--external-id")
    parser.add_argument("--event-key")
    parser.add_argument("--title")
    parser.add_argument("--scheduled-at")
    parser.add_argument("--instance")
    parser.add_argument("--game-version")
    parser.add_argument("--region")
    parser.add_argument("--realm")
    parser.add_argument("--event-id")
    args = parser.parse_args()
    config = load_config(Path(args.config))
    if args.command == "wcl-import":
        if not args.report_code:
            parser.error("wcl-import requires --report-code")
        paths = configured_paths(config)
        try:
            result = wcl.run_import(args.report_code, config, paths["db"], offline_json=Path(args.offline_json).resolve() if args.offline_json else None)
        except wcl.WclError as exc:
            print(f"WCL import failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from None
        print(f"WCL report: {result['report_code']}")
        print(f"Title/owner: {result['title'] or 'unavailable'} / {result['owner'] or 'unavailable'}")
        print(f"Start/end: {result['start']} / {result['end']}")
        print(f"Fights: {result['fights']}; characters: {result['characters']}; attendance: {result['attendance']}")
        print(f"Inserted: {sum(result['inserted'].values())}; unchanged: {result['unchanged']}")
        print(f"Raw archive: {result['archive']}")
        for name in ("Amiringo", "Medalisa", "Divinegg"):
            suffix = "/" + wcl.normalize_identity(name)
            key = next((item for item in result["character_keys"] if item.endswith(suffix)), None)
            print(f"{name}: {'found - ' + key if key else 'not found'}")
        return
    paths = configured_paths(config)
    try:
        if args.command == "roster-import":
            if not args.input: parser.error("roster-import requires --input")
            result = roster.import_roster(Path(args.input).resolve(), paths["db"])
            print("Roster import: " + "; ".join(f"{key}={result[key]}" for key in ("inserted", "updated", "unchanged", "rejected")))
            return
        if args.command == "raid-event-upsert":
            required = {"--source": args.source, "--external-id": args.external_id, "--title": args.title,
                        "--game-version": args.game_version, "--region": args.region, "--realm": args.realm}
            missing = [flag for flag, value in required.items() if not value]
            if missing: parser.error("raid-event-upsert requires " + ", ".join(missing))
            result = roster.upsert_event(paths["db"], source=args.source, external_id=args.external_id, title=args.title,
                                         scheduled_at=args.scheduled_at, instance=args.instance, game_version=args.game_version,
                                         region=args.region, realm=args.realm)
            print(f"Raid event: {result['event_key']}; {result['action']}")
            return
        if args.command == "raid-event-link-report":
            if not args.event_key or not args.report_code: parser.error("raid-event-link-report requires --event-key and --report-code")
            print(f"Raid event report link: {args.event_key}; report={args.report_code}; {roster.link_report(paths['db'], args.event_key, args.report_code)}")
            return
        if args.command == "attendance-report":
            if not args.event_key: parser.error("attendance-report requires --event-key")
            result = roster.attendance_report(paths["db"], args.event_key)
            event = result["event"]
            print(f"Raid event: {event['event_key']} - {event['title']}; instance={event['instance'] or 'unspecified'}")
            for item in result["participants"]:
                category = "guild" if item["matched_guild"] else "unmatched/PUG"
                member = f"; member={item['member_display_name']}" if item["member_display_name"] else ""
                print(f"{item['report_code']} {item['display_name']}: {category}{member}; fights={item['attended']}/{item['total_fights']}; attendance={item['attendance_percentage']:.2f}%")
            print(f"Matched guild characters: {result['matched']}; unmatched/PUG participants: {result['unmatched']}")
            return
        if args.command == "raid-helper-import":
            if not args.event_id: parser.error("raid-helper-import requires --event-id")
            result = raid_helper.run_import(args.event_id, config, paths["db"], offline_json=Path(args.offline_json).resolve() if args.offline_json else None)
            print(f"Raid-Helper event: {result['event_key']}; signups={result['signups']}; inserted={result['inserted']}; updated={result['updated']}; unchanged={result['unchanged']}")
            print(f"Sanitized raw archive: {result['archive']}")
            return
        if args.command == "raid-reconcile":
            if not args.event_key: parser.error("raid-reconcile requires --event-key")
            result = raid_helper.reconcile(paths["db"], args.event_key)
            print(f"Raid reconciliation: {result['event_key']}; signups={result['signups']}; matched={result['matched']}; unresolved={result['unresolved']}")
            for category, count in result["categories"].items(): print(f"{category}: {count}")
            return
    except (roster.RosterError, raid_helper.RaidHelperError, sqlite3.IntegrityError, OSError) as exc:
        print(f"{args.command} failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    {"update": update, "doctor": doctor, "upload": make_upload_zip}[args.command](config)


if __name__ == "__main__":
    main()
