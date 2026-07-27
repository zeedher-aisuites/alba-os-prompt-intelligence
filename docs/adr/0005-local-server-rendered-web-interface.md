# ADR 0005: Local server-rendered web interface

## Context

Stages 1–4 provide a durable PostgreSQL source of truth, pgvector retrieval,
structured recommendation, and a resumable LangGraph human-review workflow.
They were operable through CLI commands but not by a non-technical local user.
The product needs a small browser interface without duplicating the workflow
business logic or exposing technical checkpoint state.

## Decision

Use FastAPI with server-rendered Jinja2 templates, checked-in local HTMX and
Swagger UI 5.17.14 assets, minimal local JavaScript and CSS, and versioned
`/api/v1` JSON routes. Swagger initialization is also an external local asset,
so `/docs` renders under `script-src 'self'` without `unsafe-inline` or a CDN.
Both surfaces use `WebWorkflowApplicationService`, which opens an official
PostgreSQL LangGraph checkpointer only for a workflow request and delegates to
the existing workflow service. Presenters turn Pydantic read models and safe
workflow results into explicit serializable views; templates and JSON never see
ORM objects, vectors, checkpointer blobs, raw Ollama responses, system prompts,
credentials, or private reasoning.

The web application reconstructs views from PostgreSQL plus durable checkpoints
on every request. The brief readiness cache only avoids repeated `/api/tags`
calls; it is not workflow state. Its workflow-checkpoint probe opens the exact
request-scoped saver against the effective `Database` DSN and reads a harmless
probe thread, rather than treating the mere presence of tables as readiness.
PostgreSQL transactions are short and end
before embeddings, Ollama, LangGraph execution, Jinja rendering, or human wait
time. Existing Stage 4 locks, idempotent thread handling, resume compensation,
and narrow legacy reconciliation remain authoritative.

`scripts.run_web` passes Uvicorn an explicit Selector loop factory. This is
required because Uvicorn 0.36 selects Proactor on Windows for normal single
process serving even after a Selector policy is installed, while Psycopg's
asynchronous checkpointer rejects Proactor. It defaults to `127.0.0.1`,
disables reload, and restricts its supported hosts to loopback.

The local interface includes basic response headers and Jinja autoescaping, but
it deliberately has no authentication or CSRF protection. It must not be
exposed to a network. The library remains read-only. The adjacent corpus CSV
contract and validator support spreadsheet preparation only; no import is
implemented until an idempotent external identity and provenance design is
explicitly approved.

## Alternatives

React/Vue/Angular would add a Node build chain and a separate client state model
without improving the Stage 5 operational use case. A Jinja-only experience
would work but make review actions and filter updates less convenient. Direct
route access to LangGraph checkpoint tables would bypass durable workflow
invariants. Introducing LangGraph agents or a broader API is unrelated to a
single local review screen.

## Consequences

The app can be run locally by a non-technical reviewer while HTML and JSON
share the same business behavior. It remains intentionally single-machine and
does not provide user isolation, CSRF resistance, public deployment hardening,
streaming, image generation, or corpus import. A future public deployment must
revisit authentication, CSRF, TLS, host binding, rate limits, observability,
and Uvicorn worker/process ownership before exposing an ASGI endpoint.
