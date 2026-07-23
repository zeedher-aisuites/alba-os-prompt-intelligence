# Alba OS Prompt Intelligence MVP

Alba OS is a local prompt-intelligence system for turning creative briefs into
structured, evidence-backed recommendations for image and video generation
platforms. Phase 1 will use approved examples, rejected examples as explicit
counterexamples, a local Ollama model, and human review. It will not generate or
analyze images.

## Current scope

Stage 1 provides the reproducible Python toolchain, typed configuration, a
minimal FastAPI application, and durable async persistence through PostgreSQL
with pgvector. It includes Alembic migrations, concrete project and prompt
example repositories, a small deterministic seed, and real PostgreSQL tests.
Retrieval, LLM integration, LangGraph workflows, the HTML UI, and telemetry
remain later reviewable stages.

```text
Browser / API client
        |
        v
FastAPI application
        |
        +-- GET /
        +-- GET /health
        `-- GET /health/database
                    |
                    v
       SQLAlchemy async + asyncpg
                    |
                    v
          PostgreSQL 17 + pgvector
```

## Requirements

- `uv`
- Python 3.12 (managed automatically by `uv` when unavailable)
- Docker Desktop or Docker Engine with Compose

## Setup

```bash
uv python install 3.12
uv sync --dev
```

Copy `.env.example` to `.env` if local overrides are needed. Every setting uses
the `ALBA_` prefix.

## PostgreSQL

Start the PostgreSQL/pgvector service and wait for its health check:

```bash
docker compose up -d --wait postgres
docker compose ps
```

Apply the current schema:

```bash
uv run alembic upgrade head
```

PostgreSQL stores its data in the named volume
`alba-os_alba_postgres_data`. `docker compose restart postgres` and
`docker compose down` preserve that volume. The volume is managed by Docker
outside the repository and is never committed to Git.

On first initialization, Compose creates two databases:

- `alba_os` for local development;
- `alba_os_test` for destructive integration and E2E tests.

The test URL is:

```text
postgresql+asyncpg://<local-user>:<local-password>@127.0.0.1:5432/alba_os_test
```

The test database also receives the server-side marker
`alba-os-disposable-test-database`. Tests validate both its exact name and this
marker before running migrations or `TRUNCATE`; changing only a URL is not
enough to bypass the guard.

Run the small Stage 1 seed:

```bash
uv run python -m scripts.seed_database
```

The command is idempotent. It inserts two projects and six prompt examples and
reports whether each record was created or already existed. Every vector remains
`NULL`; Stage 1 does not generate embeddings.

Inspect the seeded rows:

```bash
docker compose exec postgres psql -U alba -d alba_os \
  -c "SELECT p.slug, count(e.id) FROM projects p LEFT JOIN prompt_examples e ON e.project_id = p.id GROUP BY p.slug ORDER BY p.slug;"
```

## Run locally

```bash
uv run uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/docs>, use
<http://127.0.0.1:8000/health> for process liveness, or use
<http://127.0.0.1:8000/health/database> for PostgreSQL readiness.

## Quality gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -m "not e2e"
```

Plain `uv run pytest` also excludes E2E through the project configuration.
Tests marked `postgres` use `ALBA_TEST_DATABASE_URL`, never
`ALBA_DATABASE_URL`. Integration fixtures truncate only the guarded
`alba_os_test` database.

The Docker persistence test is marked both `docker` and `e2e`. It restarts only
the Compose `postgres` service and must be requested explicitly:

```bash
uv run pytest -m "not e2e"
uv run pytest -m e2e
```

Unit-only development does not require PostgreSQL:

```bash
uv run pytest tests/unit
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ALBA_APP_NAME` | `Alba OS Prompt Intelligence MVP` | Service display name |
| `ALBA_ENVIRONMENT` | `development` | Runtime environment |
| `ALBA_DEBUG` | `false` | FastAPI debug mode |
| `ALBA_DATABASE_URL` | local `postgresql+asyncpg` URL | Async database connection |
| `ALBA_TEST_DATABASE_URL` | local URL ending in `/alba_os_test` | Guarded destructive-test connection |
| `ALBA_DATABASE_ECHO` | `false` | SQLAlchemy SQL logging |
| `ALBA_DATABASE_POOL_SIZE` | `5` | Persistent pooled connections |
| `ALBA_DATABASE_MAX_OVERFLOW` | `10` | Temporary connections above pool size |
| `ALBA_DATABASE_POOL_TIMEOUT` | `30` | Seconds to wait for a pooled connection |
| `ALBA_DATABASE_POOL_RECYCLE` | `1800` | Seconds before recycling a connection |
| `ALBA_POSTGRES_USER` | `alba` | Compose development user |
| `ALBA_POSTGRES_PASSWORD` | `alba_dev` | Compose-only development password |
| `ALBA_POSTGRES_DB` | `alba_os` | Compose database |
| `ALBA_POSTGRES_PORT` | `5432` | Published local PostgreSQL port |

The `.env.example` credentials are public local-development placeholders, not
production secrets. `.env` is ignored by Git. Database URLs are passed directly
to SQLAlchemy and are never included in application error responses. When
Compose values change, update both database URLs consistently.

## Persistence dependencies

- SQLAlchemy 2 supplies typed ORM mappings, async engines, sessions, and
  transaction boundaries.
- `asyncpg` is the PostgreSQL async driver used by SQLAlchemy.
- Alembic owns repeatable schema upgrades and downgrades.
- `pgvector` maps PostgreSQL's vector type without generating or searching
  embeddings in this stage.

## Persistence design

- `projects` owns prompt examples and generation runs.
- Project deletion is restricted while either kind of child record exists.
- `human_reviews` belong to prompt examples and cascade on example deletion.
- JSONB stores tag lists, review lists, provider parameters, and structured
  recommendation payloads that have no independent relational identity.
- Enums are readable strings protected by named database `CHECK` constraints.
- Relationships use `lazy="raise"`; callers request relation loading explicitly.
- `Database.transaction()` owns commit and rollback. Repositories only
  `flush()` and may therefore compose several operations into one transaction.
- PostgreSQL connections set their session timezone to UTC, ORM timestamps use
  `TIMESTAMP WITH TIME ZONE`, and Pydantic contracts normalize aware values to
  UTC.
- `prompt_examples.embedding` uses the schema dimension defined once in
  `app/db/constants.py` and remains nullable, derived, and rebuildable.

The decision and alternatives are recorded in
`docs/adr/0001-postgresql-pgvector.md`.

## Rebuild the database

Recreate only the application schema while keeping the PostgreSQL volume:

```bash
uv run alembic downgrade base
uv run alembic upgrade head
```

This deletes application rows. To remove the entire local volume and initialize
a truly empty PostgreSQL instance:

```bash
docker compose down --volumes
docker compose up -d --wait postgres
uv run alembic upgrade head
```

`docker compose down --volumes` is destructive and cannot recover rows from the
removed volume.

`alembic downgrade base` intentionally preserves the PostgreSQL `vector`
extension. That is safe for databases shared with other schemas. In a database
dedicated exclusively to Alba OS, an administrator may remove it manually only
after verifying no remaining vector columns depend on it.

## Limitations

This stage has no vector search, embedding generation, RAG, Ollama adapter,
LangChain agent, LangGraph workflow, image upload, HTML UI, or telemetry. It
also has no HTTP CRUD yet: repository operations are exercised through tests
and the seed script. Those capabilities are intentionally deferred to their
corresponding implementation stages.
