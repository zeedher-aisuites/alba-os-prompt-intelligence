#!/usr/bin/env bash
# Start the local Alba OS demo in one command.
#
# Default mode uses the deterministic fake providers, so the first run needs
# no Ollama models. Fake embeddings and recommendations are diagnostic only:
# they prove the workflow, retrieval, and human-review plumbing, not real
# EmbeddingGemma or Qwen quality. Use --ollama for the real local models.
#
# Usage:
#   scripts/demo.sh [--provider fake|ollama] [--ollama] [--skip-web]
#
#   ALBA_DEMO_PROVIDER=ollama scripts/demo.sh
#
# The script never downloads Ollama models and never exposes the app outside
# 127.0.0.1 (see scripts/run_web.py). Stop with Ctrl+C, then reset the demo
# data with: docker compose down --volumes
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROVIDER="${ALBA_DEMO_PROVIDER:-fake}"
SKIP_WEB=0

usage() {
  cat <<'EOF'
Usage: scripts/demo.sh [--provider fake|ollama] [--ollama] [--skip-web]

  --provider fake    Deterministic demo mode (default). No Ollama models needed.
  --provider ollama  Real local models. Requires embeddinggemma:300m and
                     qwen2.5:3b already installed in Ollama; they are never
                     downloaded automatically.
  --ollama           Shortcut for --provider ollama.
  --skip-web         Prepare Postgres, migrations, checkpoints, and demo data,
                     then exit without starting the web server.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --provider)
      PROVIDER="${2:-}"
      shift 2
      ;;
    --provider=*)
      PROVIDER="${1#--provider=}"
      shift
      ;;
    --ollama)
      PROVIDER="ollama"
      shift
      ;;
    --fake)
      PROVIDER="fake"
      shift
      ;;
    --skip-web)
      SKIP_WEB=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [ "$PROVIDER" != "fake" ] && [ "$PROVIDER" != "ollama" ]; then
  echo "Invalid provider: $PROVIDER (expected 'fake' or 'ollama')." >&2
  exit 2
fi

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    echo "$2" >&2
    exit 1
  fi
}

require_command uv "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
require_command docker "Install Docker Desktop or Docker Engine with Compose first."

if [ "$PROVIDER" = "ollama" ]; then
  require_command ollama "Install Ollama first: https://ollama.com/download"
  echo "Checking Ollama models (they are never downloaded by this script)..."
  if ! ollama list 2>/dev/null | grep -q "embeddinggemma:300m"; then
    echo "Missing Ollama model: embeddinggemma:300m" >&2
    echo "Install it with: ollama pull embeddinggemma:300m" >&2
    exit 1
  fi
  if ! ollama list 2>/dev/null | grep -q "qwen2.5:3b"; then
    echo "Missing Ollama model: qwen2.5:3b" >&2
    echo "Install it with: ollama pull qwen2.5:3b" >&2
    exit 1
  fi
fi

if [ ! -f .env ]; then
  echo "Creating .env from .env.example (change ALBA_POSTGRES_PASSWORD before sharing this machine)."
  cp .env.example .env
fi

echo "Starting PostgreSQL (provider: $PROVIDER)..."
docker compose up -d --wait postgres

echo "Installing Python dependencies..."
uv sync --dev

echo "Applying database migrations..."
uv run alembic upgrade head

echo "Setting up durable workflow checkpoints..."
uv run python -m scripts.recommendation_workflow setup

echo "Seeding demo data (idempotent)..."
uv run python -m scripts.seed_database
uv run python -m scripts.seed_retrieval_demo

if [ "$PROVIDER" = "ollama" ]; then
  echo "Rebuilding embeddings with EmbeddingGemma..."
  uv run python -m scripts.rebuild_embeddings --provider ollama
else
  echo "Rebuilding embeddings with the deterministic fake provider (diagnostic only, not EmbeddingGemma evidence)..."
  uv run python -m scripts.rebuild_embeddings --provider fake
fi

if [ "$SKIP_WEB" -eq 1 ]; then
  echo "Demo is prepared. Start the web interface with: uv run python -m scripts.run_web"
  exit 0
fi

cat <<EOF

Alba OS demo is ready (provider: $PROVIDER).
  Web interface: http://127.0.0.1:8000/
  OpenAPI docs:  http://127.0.0.1:8000/docs
  Health:        http://127.0.0.1:8000/health

Try the three one-click demo briefs on "Create a workflow".
Stop the server with Ctrl+C. Reset all demo data with: docker compose down --volumes
EOF

uv run python -m scripts.run_web
