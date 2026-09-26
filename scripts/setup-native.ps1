# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2025-2026 Afeef Janjua
param(
    [string]$VenvPath = (Join-Path $env:USERPROFILE ".venvs\zabt-backend")
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"
$template = Join-Path $root ".env.native.example"
$backend = Join-Path $root "backend"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python Launcher is required. Install Python 3.11 or newer."
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js is required."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm is required."
}

if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath $template -Destination $envFile
    Write-Host "Created $envFile from the native template."
} else {
    Write-Host "Using existing $envFile."
}

$venvParent = Split-Path -Parent $VenvPath
if (-not (Test-Path -LiteralPath $venvParent)) {
    New-Item -ItemType Directory -Path $venvParent -Force | Out-Null
}
$python = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    & py -3.11 -m venv $VenvPath
}
if (-not $?) {
    throw "Could not create the Python 3.11 environment."
}

& $python -m pip install --upgrade pip
if ($?) {
    & $python -m pip install -r (Join-Path $backend "requirements-dev.txt")
}
if (-not $?) {
    throw "Python dependency installation failed."
}

$ports = @(5432, 6379, 9000)
$listening = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $ports -contains $_.LocalPort } | Select-Object -ExpandProperty LocalPort -Unique)
foreach ($port in $ports) {
    if ($listening -contains $port) {
        Write-Host "Port $port is listening."
    } else {
        Write-Host "Port $port is not listening."
    }
}

if ($listening -contains 5432) {
    Push-Location $backend
    try {
        & $python -m alembic upgrade head
    } finally {
        Pop-Location
    }
}

Write-Host "Setup complete."
Write-Host "Start the API from $backend with: $python -m uvicorn app.main:app --reload --port 8000"
Write-Host "Start the worker with: $python -m celery -A app.worker.celery_app worker --loglevel=info"
Write-Host "Start the frontend from $root with: npm run dev:web"
