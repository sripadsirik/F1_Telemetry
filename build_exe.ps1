#Requires -Version 5.1
<#
.SYNOPSIS
    Full build pipeline for Marco — F1 25 Race Engineer.

.DESCRIPTION
    1. Builds the React/TypeScript frontend (npm ci + npm run build).
    2. Packages the Python backend + frontend into a Windows executable
       using PyInstaller.

.OUTPUTS
    dist\Marco\Marco.exe  — double-click to run

.EXAMPLE
    .\build_exe.ps1
    .\build_exe.ps1 -Clean   # remove previous dist/ and build/ first
#>

param(
    [switch]$Clean
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = $PSScriptRoot

function Write-Step([string]$msg) {
    Write-Host "`n==> $msg" -ForegroundColor Cyan
}

function Require-Command([string]$cmd) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Error "Required command not found: '$cmd'. Please install it and try again."
        exit 1
    }
}

# ── prerequisites ──────────────────────────────────────────────────────────────
Require-Command 'node'
Require-Command 'npm'
Require-Command 'python'

# ── optional clean ─────────────────────────────────────────────────────────────
if ($Clean) {
    Write-Step "Cleaning previous build artefacts"
    foreach ($d in @('dist', 'build', '__pycache__')) {
        $p = Join-Path $Root $d
        if (Test-Path $p) { Remove-Item $p -Recurse -Force; Write-Host "  Removed $p" }
    }
    $fe_dist = Join-Path $Root 'frontend\dist'
    if (Test-Path $fe_dist) { Remove-Item $fe_dist -Recurse -Force; Write-Host "  Removed $fe_dist" }
}

# ── step 1: build frontend ─────────────────────────────────────────────────────
Write-Step "Building React/TypeScript frontend"
Push-Location (Join-Path $Root 'frontend')
try {
    npm ci --prefer-offline
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed (exit $LASTEXITCODE)" }

    npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

$distDir = Join-Path $Root 'frontend\dist'
if (-not (Test-Path $distDir)) {
    Write-Error "Frontend dist not created at: $distDir"
    exit 1
}
Write-Host "  Frontend built → $distDir" -ForegroundColor Green

# ── step 2: ensure PyInstaller is available ────────────────────────────────────
Write-Step "Checking PyInstaller"
python -m PyInstaller --version 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  PyInstaller not found — installing…" -ForegroundColor Yellow
    python -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "Failed to install PyInstaller" }
}

# ── step 3: run PyInstaller ────────────────────────────────────────────────────
Write-Step "Packaging with PyInstaller"
Push-Location $Root
try {
    python -m PyInstaller marco.spec --noconfirm
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

$exe = Join-Path $Root 'dist\Marco\Marco.exe'
if (Test-Path $exe) {
    Write-Host "`n✔  Build complete!  Executable: $exe" -ForegroundColor Green
    Write-Host "   Double-click Marco.exe to start the server." -ForegroundColor White
    Write-Host "   Then open the printed URL on any device on your network." -ForegroundColor White
} else {
    Write-Error "Build finished but Marco.exe not found at: $exe"
    exit 1
}
