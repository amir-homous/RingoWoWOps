param(
    [string]$ConfigPath = "config.json"
)

$ErrorActionPreference = "Stop"

Write-Host "RingoWoWOps report update started..." -ForegroundColor Cyan

if (!(Test-Path $ConfigPath)) {
    Write-Host "Config file not found: $ConfigPath" -ForegroundColor Red
    exit 1
}

$config = Get-Content $ConfigPath | ConvertFrom-Json
$savedVariablesPath = Join-Path $config.wow_path (Join-Path $config.wow_flavor ("WTF\Account\" + $config.account + "\SavedVariables\" + $config.savedvariables_file))

if (!(Test-Path $savedVariablesPath)) {
    Write-Host "SavedVariables file not found:" -ForegroundColor Red
    Write-Host $savedVariablesPath
    exit 1
}

$rawDir = Split-Path $config.raw_output -Parent
if (!(Test-Path $rawDir)) {
    New-Item -ItemType Directory -Force -Path $rawDir | Out-Null
}

$processedDir = $config.processed_dir
if (!(Test-Path $processedDir)) {
    New-Item -ItemType Directory -Force -Path $processedDir | Out-Null
}

Write-Host "Copying SavedVariables..." -ForegroundColor Yellow
Copy-Item $savedVariablesPath $config.raw_output -Force

Write-Host "Parsing SavedVariables..." -ForegroundColor Yellow
python tools\parse_savedvariables.py $config.raw_output --out $config.processed_dir

Write-Host "Importing CSV into SQLite..." -ForegroundColor Yellow
python tools\import_to_sqlite.py $config.processed_dir --db $config.sqlite_db

Write-Host "Generating daily report..." -ForegroundColor Yellow
python tools\generate_daily_report.py --db $config.sqlite_db --out $config.daily_report

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host ("Report: " + $config.daily_report) -ForegroundColor Green
