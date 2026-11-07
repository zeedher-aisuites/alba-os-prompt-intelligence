# Alba OS Prompt Intelligence — Demo v0.1.0

Alba OS is a local prompt-intelligence system for turning creative briefs into
structured, evidence-backed recommendations for image and video generation
platforms. It retrieves approved examples and rejected failure patterns from a
local library, generates one grounded recommendation, and pauses for an
explicit human decision — approve, revise once, or reject. It does not
generate or analyze images.

> **Demo status:** this is a closed, transferable demo (v0.1.0-demo), not a
> product. It runs only on `127.0.0.1`, has no authentication, CSRF
> protection, TLS, or multi-user support, and must not be exposed to the
> internet. See [What this demo does not do](#what-this-demo-does-not-do).

> **Start here if you have never programmed:** read
> [Getting started](docs/getting-started.md) first. It is the
> step-by-step guide for first-time users: what Alba does, how to
> install Git, uv, Docker Desktop, and Ollama, how to run the demo
> with one command, how to try the three demo briefs, and how to fix
> common problems — including the Windows PowerShell ExecutionPolicy
> block. The short version below is for people who already have the
> tools installed.

## Demo in 5 minutes

Prerequisites: [Git](https://git-scm.com/downloads),
[uv](https://docs.astral.sh/uv/getting-started/installation/) (which
manages Python 3.12), and
[Docker Desktop](https://www.docker.com/products/docker-desktop/) or
Docker Engine with Compose.
[Ollama](https://ollama.com/download) is **only** needed for the
real-model mode; the default fake mode needs no models at all. See
[Getting started](docs/getting-started.md) for install checks and
troubleshooting.

```powershell
# Windows (PowerShell)
git clone -b experimental/demo-close https://github.com/zeedher-aisuites/alba-os-prompt-intelligence.git
cd alba-os-prompt-intelligence
.\scripts\demo.ps1
```

```bash
# Linux / macOS
git clone -b experimental/demo-close https://github.com/zeedher-aisuites/alba-os-prompt-intelligence.git
cd alba-os-prompt-intelligence
bash scripts/demo.sh
```

> The `-b experimental/demo-close` part matters: it downloads the
> experimental demo branch. A plain `git clone` downloads `main`,
> which does not have the demo-close work yet.

That one command starts PostgreSQL, applies migrations, sets up the durable
workflow checkpoints, seeds the demo data, rebuilds embeddings, and starts
the web interface at <http://127.0.0.1:8000/>. Open it, go to
**Create a workflow**, and use the three one-click demo briefs:

| # | Demo brief | What to do | Expected result |
| --- | --- | --- | --- |
| 1 | Approve — cobalt host | Start it, review the grounded recommendation | Approved cobalt-host evidence is retrieved; approve it at human review |
| 2 | Revise — station frames | Start it, then choose **Revise** once | The recommendation reaches human review; try feedback such as “Add more negative space without changing identity or movement.” |
| 3 | Reject — no evidence | Start it, review the low-confidence result | Cobalt Lounge has no logo examples, so no approved evidence is retrieved and confidence is capped; a safe case to reject |

Stop the server with Ctrl+C. To reset all demo data and start clean:

```bash
docker compose down --volumes
```

Then run the demo script again.

### Fake mode vs real models

- **Default — fake mode:** deterministic fake embeddings and a deterministic
  fake recommendation provider. It proves the workflow, retrieval, and
  human-review plumbing end to end. Fake results are **diagnostic only** and
  must never be reported as EmbeddingGemma or Qwen quality.
- **Real models — `--ollama`:** uses local `embeddinggemma:300m` for retrieval
  and `qwen2.5:3b` for recommendations. Both models must already be installed
  (`ollama pull embeddinggemma:300m` and `ollama pull qwen2.5:3b`); the demo
  script never downloads them and fails with clear instructions if either
  is missing.

  ```powershell
  .\scripts\demo.ps1 -Ollama
  ```

  ```bash
  bash scripts/demo.sh --ollama
  ```

### Import your own corpus

Prepare a CSV from `data/templates/prompt-corpus-v1.csv`, validate it, then
import it into an existing project. The import is idempotent (re-imports are
skipped by prompt text or by the recorded `external-id:<id>` tag) and never
generates embeddings — run `rebuild_embeddings` afterwards.

```powershell
uv run python -m scripts.validate_prompt_corpus path\to\my-corpus.csv --strict
uv run python -m scripts.import_prompt_corpus path\to\my-corpus.csv --project example-project --dry-run
uv run python -m scripts.import_prompt_corpus path\to\my-corpus.csv --project example-project --strict
```

See [docs/data/prompt-corpus-v1.md](docs/data/prompt-corpus-v1.md) for the
contract. `source_reference` and `created_at` have no storage column in this
version and are reported as not stored.

### What this demo does not do

- No authentication, CSRF protection, TLS, multi-user isolation, or public
  deployment. Do not bind it to `0.0.0.0`.
- No image generation or analysis, no ANN index, no chunking, reranking, or
  hybrid search, no multi-agent or autonomous behavior, no streaming, and no
  telemetry. The workflow is deterministic, not an autonomous agent.
- No automatic corpus import beyond the CSV importer above; the library
  remains read-only in the web interface.
- Checkpoint retention is manual: completed threads remain until an operator
  deletes them or rebuilds the dedicated checkpoint schema.
- The default password in `.env.example` (`alba_dev`) is a local-development
  placeholder. Change `ALBA_POSTGRES_PASSWORD` in your own `.env` before
  sharing the machine; `.env` is ignored by Git.

## Current scope

Stage 5 adds a local, server-rendered browser interface and a small versioned
HTTP API over the Stage 4 durable LangGraph workflow. It retrieves evidence,
generates and critiques a recommendation, pauses for an explicit human decision,
and can approve, reject, or perform one feedback-driven revision before pausing
again. PostgreSQL remains the source of truth for business runs and separately
stores technical LangGraph checkpoints. This is a deterministic workflow, not
an autonomous agent. Multiple agents, image generation, ANN indexes, and
telemetry remain later reviewable stages.

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
        `-- structured recommendation
                       |
                       v
         LangGraph StateGraph + deterministic critic
                       |
              +--------+--------+
              |                 |
       PostgreSQL checkpoint   interrupt()
              |                 |
              `--------+--------'
                       v
             approve | revise once | reject
                       |
                       v
             GenerationRun business audit
```

## Requirements

- [Git](https://git-scm.com/downloads) (to clone the repository)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Python 3.12 (managed automatically by `uv` when unavailable)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) or
  Docker Engine with Compose
- [Ollama](https://ollama.com/download) is optional: only the
  `--ollama` demo mode needs it, with the `embeddinggemma:300m` model
  for real retrieval and the `qwen2.5:3b` chat model for real
  recommendations. The default fake mode needs no Ollama models. The
  demo script never downloads models.

For install steps, checks, and troubleshooting, see
[Getting started](docs/getting-started.md).

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

## Durable human-review workflow

Apply the Stage 4 Alembic migration, then explicitly initialize the official
LangGraph checkpoint tables:

```bash
uv run alembic upgrade head
uv run python -m scripts.recommendation_workflow setup
```

Alembic creates the isolated `alba_workflow_checkpoints` schema and the unique
nullable `generation_runs.workflow_thread_id` mapping. The official
`AsyncPostgresSaver.setup()` command then owns these technical tables inside
that schema:

- `checkpoint_migrations`;
- `checkpoints`;
- `checkpoint_blobs`;
- `checkpoint_writes`.

Application startup does not run checkpoint DDL. Run `setup` after the
migration on each newly created database.

`setup` first queries `information_schema.schemata`. If the Alembic-owned
schema is missing, it stops with
`WORKFLOW_CHECKPOINT_SCHEMA_MISSING` instead of creating objects in `public`.
After the schema exists, the official saver uses `checkpoint_migrations` to
apply its table setup idempotently. A workflow command executed while those
tables are absent reports `WORKFLOW_CHECKPOINT_UNAVAILABLE`; operators can
confirm readiness with `to_regclass` or a catalog query for the four tables
listed above.

Start a workflow:

```powershell
uv run python -m scripts.recommendation_workflow start `
  --project retrieval-evaluation-lab `
  --query-type ai_influencer `
  --brief "Preserva rostro, vestido cobalt y composición editorial." `
  --constraint "Mantener identidad facial" `
  --constraint "Conservar vestido cobalt" `
  --provider fake
```

The JSON result contains distinct identifiers:

- `thread_id` is the stable durable cursor supplied to LangGraph;
- `run_id` identifies business audit data in `generation_runs`;
- `checkpoint_id` identifies one internal version of technical graph state.

Inspect the same pause from another Python process:

```bash
uv run python -m scripts.recommendation_workflow status \
  --thread-id <thread-id>
```

Resume with one closed decision:

```bash
uv run python -m scripts.recommendation_workflow resume \
  --thread-id <thread-id> \
  --decision approve

uv run python -m scripts.recommendation_workflow resume \
  --thread-id <thread-id> \
  --decision revise \
  --feedback "Increase negative space without changing identity."

uv run python -m scripts.recommendation_workflow resume \
  --thread-id <thread-id> \
  --decision reject \
  --feedback "The proposed direction is not suitable."
```

`revise` requires non-empty feedback and is allowed exactly once. A revision
uses the original bounded evidence; it does not retrieve a different precedent
set. A second revision, an invalid decision, a missing checkpoint, a duplicate
start, and a resume after completion are typed errors. Human rejection is a
completed business process with `workflow_outcome=reject`, not a technical
`failed` run.

### Resume consistency and safe reconciliation

Immediately before a human decision, both stores must agree on the paused
state: the checkpoint is `waiting_for_human` with no decision, and the linked
`GenerationRun` is also `waiting_for_human`. The CLI normalizes and validates
`--thread-id` before it looks up either store, so leading or trailing
whitespace cannot select one run and a different checkpoint configuration.

Resume first takes a short `SELECT ... FOR UPDATE` claim that changes the
business run to `running`; it does **not** hold that transaction while
LangGraph runs. The point of no return is only reached when a subsequent
checkpoint read shows a checkpoint different from the one that was paused
before the claim. If an exception occurs first and that exact checkpoint still
proves `waiting_for_human` with `human_decision=null`, the application returns
the run to `waiting_for_human` in a separate short transaction. It records a
bounded `resume_reconciliations` audit entry in `provider_parameters` and
returns the retryable public error `WORKFLOW_RESUME_NOT_ACCEPTED`.

For a legacy interrupted claim (checkpoint still paused, run incorrectly
`running`, no outcome or decision), inspect it and apply that same narrow
reconciliation explicitly:

```bash
uv run python -m scripts.recommendation_workflow reconcile \
  --thread-id <thread-id>
```

The command rejects completed, failed, decided, mismatched, or otherwise
ambiguous state; it never edits a checkpoint, recommendation, or evidence.
After a successful reconciliation, run the normal `resume` command again. If
the checkpoint was already advanced, the claim is not released: the workflow
uses its accepted-execution failure handling instead, avoiding a blind rollback
of a decision LangGraph may have persisted.

For bounded local operational diagnostics, set
`ALBA_WORKFLOW_DIAGNOSTICS=true`. It emits only the event name, thread ID, run
ID, and stable error code through Python logging. Public CLI JSON remains safe:
it contains neither tracebacks, exception messages, credentials, raw provider
responses, nor vectors.

The `human_review` node performs no database write before `interrupt()`.
LangGraph reexecutes that node on resume, so all business writes live in
separate idempotent nodes before or after it. Embeddings, Ollama calls, the
interrupt, and human wait time hold no PostgreSQL transaction or connection
open. `SELECT ... FOR UPDATE`, a transaction-scoped advisory lock, and the
unique thread mapping allow at most one terminal business decision.

The checkpoint contains only bounded JSON: request data, evidence without
vectors, recommendation, deterministic critique, feedback, stable error codes,
and UTC ISO timestamps. It excludes SQLAlchemy objects, clients, providers,
credentials, stack traces, raw model responses, and private reasoning. The
serializer disables pickle fallback and arbitrary module reconstruction.

On Windows, the workflow CLI explicitly uses a selector event loop because the
official async Psycopg saver is incompatible with the default proactor loop.
That runtime choice currently belongs only to the CLI; integration tests install
an equivalent test loop. Before exposing the workflow through FastAPI, verify
the ASGI server's Windows loop policy and move checkpointer acquisition into
the application lifespan without keeping a connection or transaction open
during human wait time.

Run the fixed nine-workflow objective evaluation:

```bash
uv run python -m scripts.evaluate_workflows \
  --project retrieval-evaluation-lab \
  --provider fake
```

The final fake-provider audit ran all 9 workflows. Eight reached an interrupt;
all 8 eligible workflows resumed successfully through 9 resume operations
because the revision case resumes twice. The expected provider failure stopped
safely before interrupt. Global expected outcomes and post-interrupt
transitions were both 100%, and 0 of 8 duplicate terminal attempts were
accepted. Median latency was 414 ms to an actual interrupt, 75 ms for direct
resume, and 177 ms for the two-operation revision path.

The same unchanged dataset with `qwen2.5:3b` ran 9 workflows. Seven reached an
interrupt and all 7 eligible workflows resumed successfully through 8 resume
operations. The expected provider failure and the prompt-injection case both
stopped safely before interrupt; the latter omitted its required
approved-evidence citation. Therefore global expected outcomes remained 8/9,
while actual post-interrupt transitions were 8/8 and 0 of 7 duplicate terminal
attempts were accepted. Median latency was 8,060 ms to an actual interrupt,
76 ms for direct resume, and 7,529 ms for the two-operation revision path. The
revision persisted feedback but did not reproduce the complete string
verbatim, so the deliberately strict deterministic incorporation metric was
0/1; this does not claim the feedback had no semantic influence.

A safe failure before interrupt remains in the global workflow metric, but it
is not a failed resume because no resume was possible or attempted. These
synthetic runtime-contract figures are not a creative-quality or universal
LangGraph/model benchmark. The opt-in Ollama workflow test validates
`qwen2.5:3b` through an actual revision without using another LLM as judge.

## Run locally

```bash
uv run python -m scripts.run_web
```

Open <http://127.0.0.1:8000/> for the local workflow interface,
<http://127.0.0.1:8000/docs> for OpenAPI, use
<http://127.0.0.1:8000/health> for process liveness, or use
<http://127.0.0.1:8000/health/database> for PostgreSQL readiness.

### Local web workflow interface

`scripts.run_web` is the official local launcher. It binds only to
`127.0.0.1` by default, has no reload mode, and reads an optional
`ALBA_WEB_PORT` (or `--port`) value. On Windows it passes Uvicorn an explicit
Selector loop factory, because Uvicorn 0.36 otherwise selects Proactor even
when the process policy is Selector; the official async Psycopg checkpointer is
incompatible with Proactor. Linux and macOS use the same compatible selector
factory without altering the process policy.

The five-minute local tour is:

1. Start PostgreSQL and apply migrations/checkpoint setup.
2. Run `uv run python -m scripts.run_web` and open <http://127.0.0.1:8000/>.
3. Select a project, enter a brief and constraints, then start a `fake`
   workflow for deterministic local testing.
4. Inspect the bounded recommendation, approved evidence, rejected warnings,
   deterministic critique, and human review actions.
5. Choose revise (with feedback), approve, or reject; reload the page or restart
   the web process to confirm the same durable thread is recovered.

The `ollama` option uses the configured local `embeddinggemma:300m` model for
retrieval and `qwen2.5:3b` for recommendation. It is slower and requires both
models to be installed. The dashboard remains renderable when a dependency is
down and the versioned API returns a safe `503` when an unavailable dependency
would make an operation impossible.

The experience library at `/library` is read-only in the web interface. It
never imports, edits, approves, embeds, or deletes prompt examples. To load
your own corpus, use the CLI importer (see
[Import your own corpus](#import-your-own-corpus)). Prepare a spreadsheet
corpus from `data/templates/prompt-corpus-v1.csv`, then inspect it without
touching the database:

```powershell
uv run python -m scripts.validate_prompt_corpus path\to\my-corpus.csv --strict
```

Read [the corpus contract](docs/data/prompt-corpus-v1.md) before preparing real
data.

`/docs` uses a checked-in copy of Swagger UI 5.17.14 under
`app/web/static/swagger-ui/5.17.14`. It loads `/openapi.json` and every
JavaScript/CSS asset from the local server, so it remains usable with the strict
`script-src 'self'` and `style-src 'self'` policy; it does not depend on a CDN.
The library and workflow history normalize blank optional filters centrally for
their HTML and `/api/v1` forms, compare textual filters case-insensitively, and
preserve active filters in previous/next pagination links.

> **Local-only security warning:** this MVP has no authentication, CSRF
> protection, TLS, or multi-user isolation. Do not expose it to the internet,
> and do not bind it to `0.0.0.0` without a separately designed deployment
> security model.

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
| `ALBA_WORKFLOW_MAX_REVISIONS` | `1` | Fixed Stage 4 human revision ceiling |
| `ALBA_WEB_PORT` | `8000` | Local server port read by `scripts.run_web` |
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
- `Jinja2` renders the local server-side workflow interface with automatic
  escaping; `python-multipart` parses ordinary browser form fields.
- `langgraph` supplies the explicit `StateGraph`, durable checkpoint boundary,
  `interrupt()`, and `Command(resume=...)` runtime.
- `langgraph-checkpoint-postgres` supplies the official
  `AsyncPostgresSaver`; no project-owned checkpointer is implemented.
- Psycopg 3 binary is the async PostgreSQL driver used only by the official
  checkpointer. SQLAlchemy business persistence continues to use `asyncpg`.

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
- LangGraph checkpoints are technical resumable state, while `generation_runs`
  are the business audit. Neither replaces the other.
- Workflow write nodes use short caller-owned transactions. The interrupt node
  is side-effect free, and terminal repository transitions retain row locks.

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
`docs/adr/0003-structured-local-recommendation.md`. Durable workflow decisions
are recorded in `docs/adr/0004-durable-langgraph-human-review.md`.

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

Stage 4 downgrade removes the exclusive `alba_workflow_checkpoints` schema with
`CASCADE`, which deletes its technical checkpoint history, and removes the
business thread mapping column. This is intentional because the schema is
owned only by Alba OS. Do not point the setting at a shared schema.

## Limitations

Embedding input is currently one canonical document per example. The Ollama
embedding request disables silent truncation, so an input beyond the model
context fails rather than receiving an embedding for undisclosed partial text.
Recommendation is not a factual oracle, and the durable graph is not an
autonomous agent. There is no chunking, reranking, hybrid keyword search, ANN
index, RAG answer generation, ReAct agent, multiple agents, open tools,
conversational memory, streaming, image generation or analysis, or telemetry.
The Stage 5 HTML interface and small read-only/versioned workflow API are local
operator surfaces, not a public CRUD product. Checkpoint
retention is manual for the MVP: completed development threads remain until an
operator calls the official thread deletion API or rebuilds the dedicated
schema; integration tests remove their own threads and truncate only after the
reserved test-database guards pass.

Changing model or dimension requires a new column/migration, complete
regeneration from `embedding_text`, a new index when applicable, retrieval
validation, and only then removal of the previous representation. Historical
migrations must not be edited.
