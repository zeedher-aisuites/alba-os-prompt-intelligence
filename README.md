# Alba OS Prompt Intelligence MVP

Alba OS is a local prompt-intelligence system for turning creative briefs into
structured, evidence-backed recommendations for image and video generation
platforms. Phase 1 will use approved examples, rejected examples as explicit
counterexamples, a local Ollama model, and human review. It will not generate or
analyze images.

## Current scope

Stage 3 adds one structured prompt-recommendation use case over the Stage 2
memory. It retrieves approved precedents and rejected failure patterns with one
query embedding, builds bounded untrusted context, validates local model JSON,
checks every evidence reference, and persists the result as a `GenerationRun`.
PostgreSQL remains the source of truth. LangGraph workflows, agents, the HTML
UI, image generation, ANN indexes, and telemetry remain later reviewable
stages.

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

EmbeddingTextBuilder --> EmbeddingProvider
                              |
                    +---------+---------+
                    |                   |
              Fake (tests)      Ollama /api/embed
                                      |
                            embeddinggemma:300m

RetrievalService --> exact cosine distance in PostgreSQL
                    +-- approved positive evidence
                    `-- rejected failure patterns

RecommendationService
        +-- one query embedding
        +-- bounded approved/rejected context
        +-- Fake or Ollama /api/chat provider
        +-- Pydantic + evidence-ID validation
        `-- completed/failed GenerationRun
```

## Requirements

- `uv`
- Python 3.12 (managed automatically by `uv` when unavailable)
- Docker Desktop or Docker Engine with Compose
- Ollama with the `embeddinggemma:300m` model for real Stage 2 backfill and
  acceptance evaluation
- Optional Ollama chat model `qwen2.5:3b` for real Stage 3 validation. The fake
  recommendation provider requires no chat model.

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
reports whether each record was created or already existed. Vectors remain
`NULL` until the explicit indexing command runs.

Inspect the seeded rows:

```bash
docker compose exec postgres psql -U alba -d alba_os \
  -c "SELECT p.slug, count(e.id) FROM projects p LEFT JOIN prompt_examples e ON e.project_id = p.id GROUP BY p.slug ORDER BY p.slug;"
```

## Embeddings and exact retrieval

Install Ollama explicitly using its supported installer, open a new terminal,
then prepare the model outside automated tests:

```bash
ollama --version
ollama pull embeddinggemma:300m
ollama list
```

Verify the local API and exact output dimension:

```powershell
$body = @{
  model = "embeddinggemma:300m"
  input = @("Alba OS embedding dimension check")
  truncate = $false
} | ConvertTo-Json
$response = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:11434/api/embed" `
  -ContentType "application/json" `
  -Body $body
$response.embeddings[0].Count
```

The final command must print `768`. Automated tests never pull models.

Create the separate 64-example retrieval demonstration dataset:

```bash
uv run python -m scripts.seed_retrieval_demo
```

The original two-project/six-example seed remains unchanged in scope. The demo
seed adds one project with eight examples for every `QueryType`: three
approved, two in review, and three rejected. Its tags contain deterministic
relevance labels used by the evaluation runner.

Preview stale work without calling a provider or changing rows:

```bash
uv run python -m scripts.rebuild_embeddings --project retrieval-evaluation-lab --dry-run
```

Backfill with the real local model:

```bash
uv run python -m scripts.rebuild_embeddings \
  --project retrieval-evaluation-lab \
  --provider ollama \
  --batch-size 16
```

Supported filters and behavior:

- `--project` accepts a project slug.
- `--status` accepts `approved`, `in_review`, or `rejected`.
- `--batch-size` controls provider batch size.
- `--force` rebuilds even current vectors.
- `--dry-run` detects work without provider calls or writes.
- `--provider fake` is only for deterministic tests and diagnostics. It is not
  evidence that EmbeddingGemma works.

The source text has a fixed section order, collapsed whitespace, sorted tags,
and consistent empty sections. SHA-256 is calculated over its exact UTF-8
bytes. An embedding is stale when its vector is missing, its source hash
changes, provider/model metadata differs, or `embedded_at` is absent.

Run exact cosine queries without exposing vectors:

```bash
uv run python -m scripts.search_examples \
  "preserve the virtual host outfit and identity" \
  --kind approved \
  --query-type ai_influencer \
  --provider ollama

uv run python -m scripts.search_examples \
  "find changed outfits and inconsistent identity" \
  --kind failure \
  --query-type ai_influencer \
  --provider ollama
```

Similarity is `1 - cosine_distance`. Approved and rejected retrieval are
separate operations. NULL vectors are ignored. Filters may restrict project,
query type, target platform, minimum similarity, and limit. Empty evidence
returns an empty list plus `insufficient_evidence=true`; it never fabricates a
match.

Run the 20-case evaluation:

```bash
uv run python -m scripts.evaluate_retrieval --provider ollama
```

The runner resolves relevant IDs from deterministic dataset tags and reports
Recall@3, Recall@5, MRR, Precision@5, zero-result rate, and measured p50/p95
latency, separately for positive and failure retrieval. Fake-provider metrics
are diagnostic only and must not be reported as EmbeddingGemma acceptance
metrics.

## Structured prompt recommendations

EmbeddingGemma remains an embedding-only model and is never used for chat.
Stage 3 configures `qwen2.5:3b` as the separate local chat model. Automated
tests never download it. Install it explicitly only when real Ollama validation
is desired:

```bash
ollama pull qwen2.5:3b
ollama list
```

Generate a deterministic recommendation while the chat model is absent:

```powershell
uv run python -m scripts.recommend_prompt `
  --project retrieval-evaluation-lab `
  --query-type ai_influencer `
  --brief "Mantén el rostro, vestido cobalt y peinado del personaje." `
  --constraint "Preserve the same face" `
  --constraint "Keep the approved outfit" `
  --provider fake
```

Use `--provider ollama` only after the configured chat model is installed. The
CLI still uses the configured EmbeddingGemma adapter for the single retrieval
embedding. It prints the run ID, structured recommendation, bounded evidence,
warnings, confidence, human-review decision, provider/model, and latency. It
never prints vectors or credentials.

The context builder assigns stable request-local IDs (`C1`, `C2`, and so on) to
constraints. The provider must account for every ID exactly once in
`covered_constraint_ids` or `unmet_constraint_ids`. Positive precedent must be
cited explicitly in `used_positive_evidence_ids`, while each rejected example
used as a warning is represented as `{evidence_id, warning}`. Unknown IDs,
cross-status evidence, duplicate accounting, overlap, and omitted constraints
are typed validation errors; references are never silently added by the
application.

The builder uses the brief and constraints as creative task data while treating
any embedded meta-instruction as untrusted. Retrieved text is also untrusted
JSON data and cannot redefine the system. Approved and rejected evidence are
separated and ordered by similarity with ID tie-breaking. The default budget is
18,000 characters:

- brief is limited to 4,000 characters;
- each of at most 20 constraints is limited to 500 characters;
- each evidence field is visibly truncated at 1,200 characters;
- only lowest-ranked evidence may be omitted to fit the total budget;
- brief and constraints are never truncated silently and instead cause a
  validation/context-budget error.

Run the fourteen-brief objective evaluation:

```bash
uv run python -m scripts.evaluate_recommendations \
  --project retrieval-evaluation-lab \
  --provider fake
```

It measures schema validity, evidence-reference validity, fabricated-reference
rate, constraint coverage, human-review decisions, no-evidence handling,
successful run persistence, structured-output repair attempts, and p50/p95
latency. Creative usefulness, tone, and visual quality still require human
evaluation; no second LLM acts as judge.

The application computes the public `confidence`; the model's
`provider_confidence` is only one bounded input and is not presented as a
statistical probability. The heuristic uses the best cited similarity, number
of cited approved examples, constraint coverage, unmet constraints, missing
citations or warnings, and whether one repair was required. With no evidence,
the application forces human review, empty evidence references, an explicit
missing-evidence statement, and `confidence <= 0.30`. Retrieved approved
evidence without a citation is treated as ungrounded, forces human review, and
caps confidence at `0.35`. The provider first spends the one shared repair
attempt asking for a valid citation; only a second omission is accepted through
that explicitly ungrounded path.

The Ollama adapter sends only the eight required draft fields and dynamically
restricts evidence and constraint IDs to those in the bounded context. Empty
allowed-ID sets are constrained to `[]`, the prompt is constrained to a
non-empty string, and no-evidence provider confidence is constrained to
`0.00-0.30`. Because Ollama 0.32.3 does not enforce the array minimum reliably,
its wire schema requests one non-empty rationale string; the adapter maps that
explicit field to the public one-item rationale list. Constraint accounting is
also represented on the wire as one required map from every `C` ID to
`covered|unmet`, making overlap impossible before it is converted to the two
public lists. Full Pydantic and grounding validation still run afterward. The
adapter does not accept an empty rationale or incomplete JSON. Schema and
grounding failures share one repair budget: at most one targeted retry.

Final local results from `Qwen 2.5 3B local, synthetic dataset of 14 briefs`
are shown below. They are a reproducible MVP diagnostic, not a universal model
benchmark or a substitute for independent creative review.

| Metric | Fake provider | Qwen 2.5 3B local |
| --- | ---: | ---: |
| Completed / total | 14 / 14 | 14 / 14 |
| Schema validity | 100% | 100% |
| Constraint accounting | 100% | 100% |
| Covered constraints | 100% | 100% |
| Positive evidence citation | 100% | 100% |
| Valid rejected-warning citation | 100% | 100% |
| Fabricated evidence IDs | 0% | 0% |
| Fabricated constraint IDs | 0% | 0% |
| No-evidence handling | 100% | 100% |
| Successful run persistence | 100% | 100% |
| Repair attempts | 0 | 0 |
| Confidence mean (range) | 0.6940 (0.25-0.82) | 0.5998 (0.10-0.8589) |
| Latency p50 | 257 ms | 8,247 ms |
| Latency p95 | 2,095.75 ms | 8,779.45 ms |

The original exhausted-repair case combined a missing positive citation with
an empty rationale on the retry. The explicit non-empty wire rationale removed
that structural failure. A later audit found that a degradable missing-citation
error could be raised before a covered/unmet overlap. The final wire accounting
map makes overlap impossible and the application now validates every hard
grounding invariant before considering safe degradation. The final Qwen run
needed no repair. The fake p95 includes one 5,479 ms embedding outlier.

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
uv run pytest -m "not e2e and not ollama"
```

Plain `uv run pytest` also excludes E2E and Ollama through the project
configuration.
Tests marked `postgres` use `ALBA_TEST_DATABASE_URL`, never
`ALBA_DATABASE_URL`. Integration fixtures truncate only the guarded
`alba_os_test` database.

The Docker persistence test is marked both `docker` and `e2e`. It restarts only
the Compose `postgres` service and must be requested explicitly:

```bash
uv run pytest -m "not e2e and not ollama"
uv run pytest -m e2e
```

The real provider check is opt-in and does not download its model:

```bash
uv run pytest -m ollama
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
| `ALBA_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Local Ollama API |
| `ALBA_EMBEDDING_MODEL` | `embeddinggemma:300m` | Exact embedding model identifier |
| `ALBA_EMBEDDING_TIMEOUT` | `30` | Provider request timeout in seconds |
| `ALBA_EMBEDDING_BATCH_SIZE` | `16` | Default document batch size |
| `ALBA_RETRIEVAL_MAX_LIMIT` | `20` | Maximum evidence rows returned |
| `ALBA_RECOMMENDATION_MODEL` | `qwen2.5:3b` | Exact local chat model identifier |
| `ALBA_RECOMMENDATION_TIMEOUT` | `60` | Local chat request timeout in seconds |
| `ALBA_RECOMMENDATION_CONTEXT_MAX_CHARACTERS` | `18000` | Total bounded context budget |
| `ALBA_RECOMMENDATION_EVIDENCE_FIELD_MAX_CHARACTERS` | `1200` | Visible per-evidence truncation limit |
| `ALBA_RECOMMENDATION_MAX_OUTPUT_TOKENS` | `1200` | Ollama structured-output token ceiling |
| `ALBA_RECOMMENDATION_MAX_REPAIR_ATTEMPTS` | `1` | Maximum schema-repair retry count |
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
  embeddings itself.
- `httpx` is a runtime dependency because the project-owned Ollama adapter
  calls local `/api/embed` and `/api/chat` endpoints asynchronously.

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
- `embedding_provider`, `embedding_model`, `embedding_source_hash`, and
  `embedded_at` make stale detection explicit.
- A database `CHECK` requires the vector and its four provenance fields to be
  all NULL or all populated. This prevents incomplete index metadata even when
  writes bypass the indexing service.
- Retrieval uses exact cosine distance first. No HNSW or IVFFlat index exists
  yet; an ANN index requires measured scale and recall evidence.
- `GenerationRunRepository` flushes but never commits. Recommendation run
  creation, evidence reads, completion, and failure updates use separate short
  transactions. Embedding and chat HTTP calls happen with no PostgreSQL
  transaction open.
- Provider-authored evidence IDs must be subsets of the bounded context.
  Provider/model columns are stamped by the application, not trusted from
  model-authored JSON.

The Stage 2 CLI deliberately keeps its caller-owned PostgreSQL transaction open
while each local Ollama batch is generated. That provides all-or-nothing
rollback across the small 64-row MVP backfill, but it also occupies a pooled
connection while waiting for HTTP. A production-scale indexer should use a
two-phase design: read immutable work items, generate vectors without an open
database transaction, then recheck each source hash and persist short batches
transactionally. Moving the HTTP call alone would be unsafe because a source
row could change between generation and persistence.

Persistence and retrieval decisions are recorded in
`docs/adr/0001-postgresql-pgvector.md` and
`docs/adr/0002-embeddinggemma-exact-retrieval.md`. Structured recommendation
decisions are recorded in
`docs/adr/0003-structured-local-recommendation.md`.

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

Embedding input is currently one canonical document per example. The Ollama
embedding request disables silent truncation, so an input beyond the model
context fails rather than receiving an embedding for undisclosed partial text.
Recommendation is one bounded call, not a factual oracle or autonomous agent.
There is no chunking, reranking, hybrid keyword search, ANN index, HTTP
recommendation endpoint, RAG answer generation, LangChain agent, LangGraph
workflow, image generation or analysis, HTML UI, or telemetry. HTTP CRUD also
remains absent.

Changing model or dimension requires a new column/migration, complete
regeneration from `embedding_text`, a new index when applicable, retrieval
validation, and only then removal of the previous representation. Historical
migrations must not be edited.
