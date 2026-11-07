# Start the local Alba OS demo in one command (Windows / PowerShell).
#
# Default mode uses the deterministic fake providers, so the first run needs
# no Ollama models. Fake embeddings and recommendations are diagnostic only:
# they prove the workflow, retrieval, and human-review plumbing, not real
# EmbeddingGemma or Qwen quality. Use -Ollama for the real local models.
#
# Usage:
#   .\scripts\demo.ps1
#   .\scripts\demo.ps1 -Ollama
#   .\scripts\demo.ps1 -Provider ollama -SkipWeb
#   $env:ALBA_DEMO_PROVIDER = "ollama"; .\scripts\demo.ps1
#
# The script never downloads Ollama models and never exposes the app outside
# 127.0.0.1 (see scripts/run_web.py). Stop with Ctrl+C, then reset the demo
# data with: docker compose down --volumes
param(
    [ValidateSet("fake", "ollama")]
    [string]$Provider = $(if ($env:ALBA_DEMO_PROVIDER) { $env:ALBA_DEMO_PROVIDER } else { "fake" }),
    [switch]$Ollama,
    [switch]$Fake,
    [switch]$SkipWeb
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if ($Ollama) { $Provider = "ollama" }
if ($Fake) { $Provider = "fake" }

function Fail($Message) {
    Write-Error $Message
    exit 1
}

function Require-Command($Name, $Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Fail "Missing required command: $Name. $Hint"
    }
}

Require-Command "uv" "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
Require-Command "docker" "Install Docker Desktop first."

if ($Provider -eq "ollama") {
    Require-Command "ollama" "Install Ollama first: https://ollama.com/download"
    Write-Host "Checking Ollama models (they are never downloaded by this script)..."
    $models = ollama list
    if ($models -notmatch "embeddinggemma:300m") {
        Fail "Missing Ollama model: embeddinggemma:300m. Install it with: ollama pull embeddinggemma:300m"
    }
    if ($models -notmatch "qwen2.5:3b") {
        Fail "Missing Ollama model: qwen2.5:3b. Install it with: ollama pull qwen2.5:3b"
    }
}

if (-not (Test-Path ".env")) {
    Write-Host "Creating .env from .env.example (change ALBA_POSTGRES_PASSWORD before sharing this machine)."
    Copy-Item ".env.example" ".env"
}

Write-Host "Starting PostgreSQL (provider: $Provider)..."
docker compose up -d --wait postgres

Write-Host "Installing Python dependencies..."
uv sync --dev

Write-Host "Applying database migrations..."
uv run alembic upgrade head

Write-Host "Setting up durable workflow checkpoints..."
uv run python -m scripts.recommendation_workflow setup

Write-Host "Seeding demo data (idempotent)..."
uv run python -m scripts.seed_database
uv run python -m scripts.seed_retrieval_demo

if ($Provider -eq "ollama") {
    Write-Host "Rebuilding embeddings with EmbeddingGemma..."
    uv run python -m scripts.rebuild_embeddings --provider ollama
} else {
    Write-Host "Rebuilding embeddings with the deterministic fake provider (diagnostic only, not EmbeddingGemma evidence)..."
    uv run python -m scripts.rebuild_embeddings --provider fake
}

if ($SkipWeb) {
    Write-Host "Demo is prepared. Start the web interface with: uv run python -m scripts.run_web"
    exit 0
}

Write-Host ""
Write-Host "Alba OS demo is ready (provider: $Provider)."
Write-Host "  Web interface: http://127.0.0.1:8000/"
Write-Host "  OpenAPI docs:  http://127.0.0.1:8000/docs"
Write-Host "  Health:        http://127.0.0.1:8000/health"
Write-Host ""
Write-Host "Try the three one-click demo briefs on `"Create a workflow`"."
Write-Host "Stop the server with Ctrl+C. Reset all demo data with: docker compose down --volumes"

uv run python -m scripts.run_web
