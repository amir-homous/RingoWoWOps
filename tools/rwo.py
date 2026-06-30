import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path


DEFAULT_CONFIG = Path("config.json")


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def savedvariables_path(config: dict) -> Path:
    return (
        Path(config["wow_path"])
        / config.get("wow_flavor", "_anniversary_")
        / "WTF"
        / "Account"
        / config["account"]
        / "SavedVariables"
        / config.get("savedvariables_file", "RingoWoWOps.lua")
    )


def update(config: dict) -> None:
    src = savedvariables_path(config)
    if not src.exists():
        raise FileNotFoundError(f"SavedVariables file not found: {src}")

    raw_output = Path(config.get("raw_output", "data/raw/RingoWoWOps.lua"))
    processed_dir = Path(config.get("processed_dir", "data/processed"))
    sqlite_db = Path(config.get("sqlite_db", "data/ringo_ops.sqlite"))
    daily_report = Path(config.get("daily_report", "data/processed/daily_report.md"))

    raw_output.parent.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    print(f"Copying {src} -> {raw_output}")
    shutil.copy2(src, raw_output)

    run([sys.executable, "tools/parse_savedvariables.py", str(raw_output), "--out", str(processed_dir)])
    run([sys.executable, "tools/import_to_sqlite.py", str(processed_dir), "--db", str(sqlite_db)])
    run([sys.executable, "tools/generate_daily_report.py", "--db", str(sqlite_db), "--out", str(daily_report)])

    print(f"Report ready: {daily_report}")


def doctor(config: dict) -> None:
    checks = [
        ("WoW path", Path(config["wow_path"])),
        ("SavedVariables", savedvariables_path(config)),
        ("Parser", Path("tools/parse_savedvariables.py")),
        ("SQLite importer", Path("tools/import_to_sqlite.py")),
        ("Daily report generator", Path("tools/generate_daily_report.py")),
    ]

    ok = True
    for name, path in checks:
        exists = path.exists()
        status = "OK" if exists else "MISSING"
        print(f"{name}: {status} - {path}")
        ok = ok and exists

    if not ok:
        raise SystemExit(1)


def make_upload_zip(config: dict) -> None:
    update(config)

    processed_dir = Path(config.get("processed_dir", "data/processed"))
    raw_output = Path(config.get("raw_output", "data/raw/RingoWoWOps.lua"))

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("data/upload")
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"RingoWoWOps_upload_{stamp}.zip"

    candidates = [
        raw_output,
        processed_dir / "daily_report.md",
        processed_dir / "sessions.csv",
        processed_dir / "snapshots.csv",
        processed_dir / "notes.csv",
        processed_dir / "activities.csv",
        processed_dir / "events.csv",
    ]

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for file in candidates:
            if file.exists():
                z.write(file, file.as_posix())

    print(f"Upload package ready: {zip_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="RingoWoWOps local helper CLI")
    parser.add_argument("command", choices=["update", "doctor", "upload"], help="Command to run")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to config.json")
    args = parser.parse_args()

    config = load_config(Path(args.config))

    if args.command == "update":
        update(config)
    elif args.command == "doctor":
        doctor(config)
    elif args.command == "upload":
        make_upload_zip(config)


if __name__ == "__main__":
    main()
