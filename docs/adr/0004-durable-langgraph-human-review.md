# ADR 0004: Durable LangGraph workflow with human review

## Context

Stage 3 is one bounded recommendation call. It needs no graph while it remains
linear. Stage 4 introduces actual orchestration requirements: multiple explicit
steps, deterministic branching, an indefinite human pause, restart-safe
resumption, one feedback-driven revision, and concurrency around terminal
decisions.

Application processes may stop while a reviewer waits for hours or days.
Holding Python memory, a PostgreSQL connection, or a database transaction
during that wait is unacceptable. A `GenerationRun` records the business
outcome but is not a complete technical execution cursor.

The workflow still handles untrusted briefs, constraints, retrieved text, and
LLM output. It must not serialize providers, clients, ORM objects, vectors,
secrets, raw responses, stack traces, or private reasoning.

## Decision

### Graph API and orchestration boundary

Use LangGraph 1.2's Graph API with an explicit `StateGraph`. The Functional API
is not used because named nodes and visible conditional routes make the
workflow topology, checkpoint boundaries, and side-effect placement easier to
review.

The graph is:

```text
START
  -> initialize_workflow
  -> retrieve_evidence
  -> generate_recommendation
  -> critique_recommendation
       -> hard failure -> fail_workflow -> END
       -> prepare_human_review
       -> human_review -> interrupt()
            -> approve -> complete_workflow -> END
            -> reject  -> reject_workflow -> END
            -> revise  -> revise_recommendation
                       -> critique_recommendation
                       -> prepare_human_review
                       -> human_review -> interrupt()
```

Routing uses only application enums and deterministic conditions. This is not
an agent, has no open tools, and has no model-selected route.

Nodes reuse `RecommendationService`, which itself reuses the project-owned
embedding provider, retrieval service, context builder, recommendation
provider, Pydantic grounding, and operational-confidence policy. Retrieval
does not know about LangGraph or the chat provider. The provider does not know
about PostgreSQL.

### State

`RecommendationWorkflowState` is an explicit `TypedDict`. It stores only JSON
values needed to resume:

- workflow, thread, run, and project identifiers;
- the validated request;
- current phase;
- bounded recommendation context and positive/failure evidence;
- validated recommendation and deterministic critique;
- revision count;
- human decision and feedback;
- one stable error code;
- UTC ISO timestamps.

The state deliberately duplicates a small evidence projection already present
inside the bounded context because it is part of the directly inspectable
workflow contract. It never stores vector values, SQLAlchemy sessions or
entities, engines, providers, HTTP clients, credentials, raw model responses,
stack traces, or private chain-of-thought.

The default `JsonPlusSerializer` is configured without pickle fallback and
with no allowed arbitrary msgpack modules. The current state therefore remains
portable JSON rather than executable object reconstruction.

### Deterministic critic

`RecommendationCritic` is a second deterministic validation layer, not a
second LLM. It checks schema-backed content, complete constraint accounting,
valid evidence roles and IDs, warnings, operational confidence, missing
evidence, unmet constraints, required human review, an empty prompt, and
incompatible states.

It returns typed `passed`, `hard_failures`, `review_reasons`, `warnings`, and a
closed route. It never rewrites the prompt. Existing Stage 3 grounding remains
authoritative; the critic provides defense in depth.

### PostgreSQL checkpoints

Use the official `langgraph-checkpoint-postgres` 3.1
`AsyncPostgresSaver`. Do not implement a project-owned saver and do not use an
in-memory saver for durability acceptance.

Alembic creates the exclusive `alba_workflow_checkpoints` schema. The explicit
CLI `setup` command invokes the official idempotent saver setup after Alembic;
application startup does not run DDL. Version 3.1 creates and migrates:

- `checkpoint_migrations`;
- `checkpoints`;
- `checkpoint_blobs`;
- `checkpoint_writes`.

The PostgreSQL schema isolates technical runtime tables from business tables.
The root graph uses LangGraph's empty `checkpoint_ns`; non-empty namespaces are
reserved for actual subgraph paths in the installed API.

The three identifiers have different meanings:

- `thread_id` is a stable durable cursor and is unique in
  `generation_runs.workflow_thread_id`;
- `run_id` is the UUID of one business audit row;
- `checkpoint_id` is one internal version in a LangGraph thread history.

Checkpoint retention is manual for the MVP. Integration tests delete their
threads and guarded test cleanup truncates technical state while retaining the
checkpointer migration table. A later retention job may delete old completed
threads through the official API.

### Interrupt and revision

Use the official `interrupt()` and resume with `Command(resume=...)`. The
interrupt payload is a validated JSON contract containing only workflow/run
IDs, the recommendation, rationale, constraint accounting, bounded evidence,
warnings, confidence, critic findings, revision count, and the three valid
options.

LangGraph restarts the node containing `interrupt()` from its beginning during
resume. Therefore `human_review` performs no database effect before the
interrupt. A preceding idempotent node saves the `waiting_for_human` business
state. Resume payloads are validated by Pydantic before the business row is
claimed.

`revise` requires non-empty feedback. One revision reuses the exact original
evidence and appends feedback inside explicit untrusted-data delimiters. It
passes through the same provider, grounding, confidence, critic, and human
interrupt. A second revision is rejected before checkpoint mutation.

Approve completes the business run. Human reject also completes the workflow
but records `workflow_outcome=reject` in JSONB; it is not a technical failure.
This avoids changing the existing closed `RunStatus` vocabulary merely to
represent a review outcome.

### Business persistence, transactions, and concurrency

LangGraph checkpoints do not replace `generation_runs`.

`GenerationRun` receives one nullable unique `workflow_thread_id`. The column
is a real schema requirement: JSONB or the non-unique 32-character `trace_id`
cannot prevent two business runs from claiming one durable thread.

Initialization uses a transaction-scoped PostgreSQL advisory lock derived from
the thread ID, checks the unique mapping, and can safely recover its own
workflow ID after a node replay. Repository methods flush but never commit.
Caller-owned transactions remain short.

Before resume, `claim_human_resume` locks the run row with
`SELECT ... FOR UPDATE` and transitions `waiting_for_human` to `running`.
Concurrent approve/reject commands therefore have at most one winner; the
loser sees `INVALID_RUN_TRANSITION`. Terminal write nodes are idempotent for
LangGraph replay.

The claim and a LangGraph checkpoint write cannot share one atomic transaction,
so resume has a deliberately narrow compensation rule. The service validates
and trims `thread_id` before both stores are addressed, retains the paused
checkpoint ID, then issues the short claim. The point of no return is a later
checkpoint read that proves a different checkpoint was persisted. If invoking
`Command(resume=...)` raises before that point, and the exact original
checkpoint still says `waiting_for_human` with no human decision, a second
short transaction restores the run to `waiting_for_human`. It adds a bounded,
safe `resume_reconciliations` audit record containing only a stable code,
checkpoint ID, and UTC timestamp. The public result is the retryable
`WORKFLOW_RESUME_NOT_ACCEPTED` error.

This compensation is intentionally rejected when the checkpoint advanced, the
run has an outcome/error/decision, the thread mapping differs, or any required
precondition is absent. That avoids blindly rolling back a decision that
LangGraph may have accepted. The explicit `reconcile` CLI command is the same
typed mechanism for a legacy paused-checkpoint/running-run split; it never
modifies the checkpoint, recommendation, or evidence. If checkpoint storage is
unavailable, the service does not pretend it can prove non-acceptance; the
operation remains unavailable until it can be inspected safely.

No business transaction remains open during embedding, retrieval provider I/O,
Ollama chat, interrupt, human wait, or process downtime. Retrieval reads use a
short transaction; every status change uses its own short write transaction.

### Errors and Windows runtime

Known provider and application errors retain stable codes. Unknown failures
use `WORKFLOW_EXECUTION_FAILED`. Business JSON never stores exception text,
credentials, stack traces, or raw provider payloads.

The official async saver uses Psycopg 3. On Windows, Psycopg requires a selector
event loop rather than the default proactor loop. CLI entry points use
`asyncio.Runner(loop_factory=asyncio.SelectorEventLoop)`, and integration tests
register the equivalent current pytest-asyncio loop factory hook.

This event-loop adaptation is currently limited to the CLI and integration
tests. A future FastAPI workflow endpoint must verify the ASGI server's Windows
loop policy and manage the saver through application lifespan resources before
it can be considered supported. It must not keep a saver connection or business
transaction open while waiting for human input.

The explicit setup first checks `information_schema.schemata`. Before the
Alembic migration it raises `WORKFLOW_CHECKPOINT_SCHEMA_MISSING`; if the schema
exists but official tables have not been initialized, workflow operations
translate the database failure to `WORKFLOW_CHECKPOINT_UNAVAILABLE`. Operators
can inspect the four expected tables or use `to_regclass`. The saver migration
table makes repeated setup idempotent.

## Alternatives

- Keeping workflow state only in Python memory was rejected because process
  restart would lose the human pause.
- Using `InMemorySaver` for durability tests was rejected because it cannot
  prove PostgreSQL persistence or restart recovery.
- Writing a custom SQLAlchemy checkpointer was rejected because it would
  duplicate the official checkpoint protocol and migrations.
- Using the Functional API was rejected because named nodes and conditional
  edges are clearer for this bounded review workflow.
- Reusing `trace_id` as the durable key was rejected because it is optional,
  non-unique, shorter, and has a different observability meaning.
- Storing human rejection as `failed` was rejected because review rejection is
  not a provider, validation, or infrastructure error.
- A second LLM critic was rejected because deterministic invariants need
  deterministic enforcement.
- Unlimited revisions, reflection loops, ReAct, agents, and open tools were
  rejected because they would make routing and cost unbounded.

## Consequences

The workflow can pause in PostgreSQL, be inspected from another process, and
resume after Python or PostgreSQL restarts. A real E2E test restarts the
Compose PostgreSQL service and confirms the same checkpoint remains available.

Two PostgreSQL drivers coexist intentionally: SQLAlchemy business persistence
uses `asyncpg`, while the official saver requires Psycopg. This adds dependency
weight and a Windows event-loop constraint.

The Stage 4 migration is reversible. Its downgrade removes the unique thread
mapping and drops the exclusive checkpoint schema with `CASCADE`, deleting
technical history. This is safe only because the schema is dedicated to Alba
OS and must not be shared with another application.

The fixed nine-workflow fake-provider evaluation measures checkpoint
persistence, resume, transition validity, duplicate terminal decisions,
feedback incorporation, failed-run persistence, and latency. In the final
audit, 8 workflows reached interrupt and all resumed through 9 resume
operations; the ninth was the expected safe provider failure. Global expected
outcomes and post-interrupt transitions were 100%, and 0 of 8 duplicate
terminal attempts were accepted. Median latency was 414 ms to an actual
interrupt, 75 ms for direct resume, and 177 ms for the two-operation revision
path.

The unchanged Qwen 2.5 3B dataset had 7 workflows reach interrupt and all 7
resumed through 8 resume operations. The expected provider failure and the
prompt-injection case stopped safely before interrupt, so expected global
outcomes were 8/9 while actual post-interrupt transitions were 8/8; 0 of 7
duplicate terminal attempts were accepted. Median latency was 8,060 ms to an
actual interrupt, 76 ms for direct resume, and 7,529 ms for the two-operation
revision path. The revision persisted feedback but did not reproduce the
complete string verbatim, so the strict deterministic incorporation metric was
0/1.

A safe pre-interrupt failure remains visible in the global workflow metric but
is excluded from resume success and resume latency because no resume was
possible or attempted. These are synthetic runtime-contract metrics, not a
universal LangGraph benchmark or an assessment of creative quality.
Independent human review remains necessary.

Stage 4 has no HTTP workflow endpoint, UI, streaming, conversational memory,
multiple agents, open tools, image generation, multimodal analysis, telemetry,
or automated checkpoint-retention job.
