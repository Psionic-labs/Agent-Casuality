<#
.SYNOPSIS
    Runs every Phase 3 validation layer in order.

.DESCRIPTION
    Layers executed:
      1. Phase 3 unit and property tests (reducer, snapshots, slicing, CLI)
      2. Full unit suite (regression guard, integration auto-skipped)
      3. Ruff and ty static gates
      4. Fixture acceptance checks driven through the real CLI, asserting
         on actual output (slice A4 == the nine fixture events, decision
         evidence, reconstruction)
      5. Real PostgreSQL integration test, only when DATABASE_URL is set
         (loaded from .env). One automatic retry absorbs transient
         hosted-database DNS/connection flakes.

.PARAMETER SkipIntegration
    Skip layer 5 even when DATABASE_URL is available.

.PARAMETER SkipStaticChecks
    Skip layer 3 (ruff / ty).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\test_phase3.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\test_phase3.ps1 -SkipIntegration
#>
param(
    [switch]$SkipIntegration,
    [switch]$SkipStaticChecks
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$env:UV_CACHE_DIR = Join-Path $repoRoot ".uv-cache"

$script:failures = 0


function Invoke-Phase3Step {
    param([string]$Name, [scriptblock]$Action)

    Write-Host ""
    Write-Host "=== $Name ===" -ForegroundColor Cyan
    $ok = $false
    try {
        $ok = & $Action
    }
    catch {
        Write-Host $_.Exception.Message -ForegroundColor DarkGray
    }
    if ($ok) {
        Write-Host "[PASS] $Name" -ForegroundColor Green
    }
    else {
        Write-Host "[FAIL] $Name" -ForegroundColor Red
        $script:failures++
    }
}


function Show-OutputTail([string]$output) {
    $lines = $output.TrimEnd() -split "`r?`n"
    Write-Host ($lines | Select-Object -Last 1)
}


function Import-DotEnv {
    if (Test-Path ".env") {
        Get-Content .env | ForEach-Object {
            $parts = $_ -split '=', 2
            if ($parts.Length -eq 2 -and $parts[0].Trim()) {
                [System.Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1], 'Process')
            }
        }
    }
}


# Layer 1 -------------------------------------------------------------------

Invoke-Phase3Step "Phase 3 unit and property tests (reducer, slicing, CLI)" {
    $out = uv run pytest tests/test_reducer.py tests/test_slicing.py tests/test_cli.py -q 2>&1 |
        Out-String
    if ($LASTEXITCODE -ne 0) { Write-Host $out; return $false }
    Show-OutputTail $out
    return $true
}


# Layer 2 -------------------------------------------------------------------

Invoke-Phase3Step "Full unit suite (integration tests auto-skip here)" {
    $out = uv run pytest -q 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { Write-Host $out; return $false }
    Show-OutputTail $out
    return $true
}


# Layer 3 -------------------------------------------------------------------

if ($SkipStaticChecks) {
    Write-Host ""
    Write-Host "=== Static checks skipped (-SkipStaticChecks) ===" -ForegroundColor Yellow
}
else {
    Invoke-Phase3Step "Ruff lint" {
        $out = uv run ruff check . 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) { Write-Host $out; return $false }
        return $true
    }

    Invoke-Phase3Step "ty type check" {
        $out = uv run ty check . 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) { Write-Host $out; return $false }
        return $true
    }
}


# Layer 4 -------------------------------------------------------------------

$fixtureArgs = @("--fixture", "fixture/fixture.json")

Invoke-Phase3Step "Fixture acceptance: slice A4 returns exactly the nine ground-truth events" {
    $out = uv run python -m cli.main @fixtureArgs slice A4 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { Write-Host $out; return $false }
    if (-not $out.Contains("9 events")) { Write-Host $out; throw "expected '9 events' in slice output" }
    $expectedIds = "A1, B1, C1, B2, C2, B3, C3, A3, A4"
    if (-not $out.Contains($expectedIds)) { Write-Host $out; throw "expected '$expectedIds' in slice output" }
    if ($out.Contains("D1")) { Write-Host $out; throw "unrelated agent D leaked into the slice" }
    return $true
}

Invoke-Phase3Step "Fixture acceptance: why exposes declared cross-agent merge inputs" {
    $out = uv run python -m cli.main @fixtureArgs why A3 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { Write-Host $out; return $false }
    foreach ($needle in @("declared_inputs", '"source_event_id": "B3"', '"source_event_id": "C3"', "structural evidence only")) {
        if (-not $out.Contains($needle)) { Write-Host $out; throw "expected '$needle' in why output" }
    }
    return $true
}

Invoke-Phase3Step "Fixture acceptance: reconstruct folds recorded state deterministically" {
    $out = uv run python -m cli.main @fixtureArgs reconstruct B 4 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { Write-Host $out; return $false }
    if (-not $out.Contains("status=active")) { Write-Host $out; throw "expected status=active" }
    if (-not $out.Contains('"customer_status":"eligible"')) {
        Write-Host $out
        throw "expected recorded tool output folded into reconstructed state"
    }
    return $true
}

Invoke-Phase3Step "Fixture acceptance: agents listing" {
    $out = uv run python -m cli.main @fixtureArgs agents 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { Write-Host $out; return $false }
    foreach ($needle in @("planner", "researcher", "coder", "background_monitor")) {
        if (-not $out.Contains($needle)) { Write-Host $out; throw "expected agent role '$needle'" }
    }
    return $true
}


# Layer 5 -------------------------------------------------------------------

Invoke-Phase3Step "PostgreSQL integration (real database, one transient-failure retry)" {
    if ($SkipIntegration) {
        Write-Host "skipped by -SkipIntegration" -ForegroundColor Yellow
        return $true
    }
    Import-DotEnv
    if (-not $env:DATABASE_URL) {
        Write-Host "skipped: set DATABASE_URL (or .env) to enable" -ForegroundColor Yellow
        return $true
    }
    $maxAttempts = 2
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        $out = uv run pytest tests/test_postgres_integration.py -m integration -q 2>&1 | Out-String
        if ($LASTEXITCODE -eq 0) {
            Show-OutputTail $out
            return $true
        }
        if ($attempt -lt $maxAttempts) {
            Write-Host "attempt $attempt failed; hosted databases occasionally drop DNS," -ForegroundColor Yellow
            Write-Host "retrying once..." -ForegroundColor Yellow
        }
    }
    Write-Host $out
    return $false
}


# Summary -------------------------------------------------------------------

Write-Host ""
Write-Host ("=" * 60)
if ($script:failures -eq 0) {
    Write-Host "All Phase 3 checks passed." -ForegroundColor Green
    exit 0
}
else {
    Write-Host "$($script:failures) Phase 3 check(s) FAILED." -ForegroundColor Red
    exit 1
}
