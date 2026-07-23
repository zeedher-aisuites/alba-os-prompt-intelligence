# Alba OS Prompt Intelligence MVP

Alba OS is a local prompt-intelligence system for turning creative briefs into
structured, evidence-backed recommendations for image and video generation
platforms. Phase 1 will use approved examples, rejected examples as explicit
counterexamples, a local Ollama model, and human review. It will not generate or
analyze images.

## Current scope

Stage 0 provides the reproducible Python toolchain, typed configuration, a
minimal FastAPI application, and automated quality gates. Persistence, retrieval,
LLM integration, LangGraph workflows, the web UI, telemetry, and container
orchestration belong to later reviewable stages.

```text
Browser / API client
        |
        v
FastAPI application
        |
        +-- GET /
        `-- GET /health
```

## Requirements

- `uv`
- Python 3.12 (managed automatically by `uv` when unavailable)

## Setup

```bash
uv python install 3.12
uv sync --dev
```

Copy `.env.example` to `.env` if local overrides are needed. Every setting uses
the `ALBA_` prefix.

## Run locally

```bash
uv run uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/docs> or check
<http://127.0.0.1:8000/health>.

## Quality gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ALBA_APP_NAME` | `Alba OS Prompt Intelligence MVP` | Service display name |
| `ALBA_ENVIRONMENT` | `development` | Runtime environment |
| `ALBA_DEBUG` | `false` | FastAPI debug mode |

## Limitations

This bootstrap has no database, RAG, Ollama adapter, LangChain agent,
LangGraph workflow, image upload, HTML UI, or telemetry. Those capabilities are
intentionally deferred to their corresponding implementation stages.

