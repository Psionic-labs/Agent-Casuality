$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$env:UV_CACHE_DIR = Join-Path $repoRoot ".uv-cache"

# Load .env file into environment
if (Test-Path ".env") {
    Get-Content .env | ForEach-Object {
        $parts = $_ -split '=', 2
        if ($parts.Length -eq 2) {
            [System.Environment]::SetEnvironmentVariable($parts[0], $parts[1], 'Process')
        }
    }
}

Write-Host "Running tests..." -ForegroundColor Cyan
uv run pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Running Ruff..." -ForegroundColor Cyan
uv run ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Running ty..." -ForegroundColor Cyan
uv run ty check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "All checks passed." -ForegroundColor Green
