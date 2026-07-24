# ADR 0003: Structured local prompt recommendation

## Context

Stage 2 can retrieve approved prompt evidence and rejected failure patterns,
but retrieval alone does not turn a creative brief into a usable prompt.
Stage 3 needs one local generation boundary that remains grounded, measurable,
and persistable without introducing agent orchestration.

Retrieved text and user briefs are untrusted. A model may return malformed JSON
or fabricate evidence identifiers. Slow local inference must not hold a
PostgreSQL write transaction open.

## Decision

Retrieval and recommendation remain separate services. `RecommendationService`
creates one query embedding, reuses it for approved and rejected exact
retrieval, builds a bounded `RecommendationContext`, invokes a project-owned
`RecommendationProvider`, validates the result, and persists one
`GenerationRun`.

The provider contract returns a `RecommendationDraft`. The application adds
the authoritative provider and model fields afterward. This prevents
model-authored JSON from claiming a different runtime.

`FakeRecommendationProvider` is deterministic and supports normal tests and
demonstrations. `OllamaRecommendationProvider` calls `/api/chat` without
streaming and requests the Pydantic JSON Schema directly. The configured local
chat model is `qwen2.5:3b`, selected as a relatively small multilingual
instruction model with documented structured JSON capability. It is separate
from the embedding-only `embeddinggemma:300m`. Models are never downloaded by
the application or tests.

The adapter validates non-empty JSON with Pydantic. Schema and dynamic
grounding/accounting failures share one repair budget: at most one additional,
targeted request containing the validation errors and the allowed IDs.
Connection failures and model mismatches fail explicitly; there is no model
fallback, loop, reflection, or agent.

Ollama 0.32.3 cannot compile several Pydantic validation keywords such as
string, array, and numeric bounds into its structured-output grammar. The
adapter therefore derives an Ollama-compatible projection with only the eight
required provider-authored fields. It dynamically enumerates allowed evidence
and constraint IDs, forces reference arrays to `[]` when no matching IDs
exist, requires a non-empty prompt with the supported `^.+$` pattern, and
enumerates confidence values between zero and one (at most `0.30` with no
evidence). Ollama does not reliably enforce the public rationale array minimum,
so the adapter's explicit wire contract requests one non-empty rationale
string and maps it to the public one-item list. The wire contract also requires
one object that maps every allowed constraint ID to exactly one of `covered` or
`unmet`; the adapter converts that object into the two public lists. This makes
overlap impossible at generation time while Pydantic and application grounding
remain authoritative afterward. The adapter does not accept an empty rationale
or partial JSON. Optional Pydantic fields keep application-owned defaults.

The context is deterministic JSON between explicit untrusted-data boundaries.
The brief and constraints are creative task data, but embedded
meta-instructions cannot change system rules, invent IDs, or reveal hidden
data. Retrieved prompts, rejection reasons, IDs, and delimiter-like strings are
untrusted data rather than instructions. Approved and rejected evidence are
separate. Vectors, ORM objects, credentials, and stack traces are excluded.

Critical input is bounded by Pydantic: the brief is at most 4,000 characters,
there are at most 20 constraints, and each constraint is at most 500
characters. Critical fields are never silently truncated. Evidence fields may
be visibly truncated at the configured per-field limit. If the total context
still exceeds 18,000 characters, lowest-similarity evidence is omitted
deterministically and omission counts are supplied. If critical data alone
cannot fit, the request fails clearly.

Constraints receive stable request-local IDs (`C1` through `Cn`). Every ID
must occur exactly once across `covered_constraint_ids` and
`unmet_constraint_ids`; unknown, overlapping, duplicate, and omitted IDs fail
with typed errors. Positive precedent must be cited explicitly through
`used_positive_evidence_ids`. Rejected evidence may only appear in a structured
`{evidence_id, warning}` entry. Unknown IDs and approved/rejected status
crossovers fail the run. The application does not silently add citations or
warnings omitted by the model.

Public `confidence` is an application heuristic, not a calibrated probability
and not a model-authored truth. It combines best cited similarity, cited
evidence count, constraint coverage, unmet constraints, missing positive
citations, missing rejected warnings, the no-evidence state, one repair
penalty, and bounded `provider_confidence`. Missing positive citations force
review and cap confidence at `0.35`; unmet constraints and missing rejected
warnings cap it at `0.50`. With no evidence, the application deterministically
requires human review, keeps evidence references empty, states that project
evidence is absent, and caps confidence at `0.30`.

If approved evidence exists but the provider cites none, the shared repair
attempt explicitly requests a citation. A second omission may be returned only
as an ungrounded recommendation with mandatory review and the `0.35` cap; the
application never inserts an ID on the model's behalf.

The existing `generation_runs` table can represent this use case, so Stage 3
adds no migration. A short transaction creates a running row. Embedding,
context construction, and the LLM call happen without a PostgreSQL transaction.
A short final transaction rechecks the running state and marks it completed.
Known failures are recorded in another short transaction using stable error
codes. Terminal transitions lock the run row with `SELECT ... FOR UPDATE`; a
concurrent terminal transition wins and the second observes the new state and
is rejected.

The persisted recommendation contains the public structured result and bounded
retrieval provenance. It does not contain vectors, credentials, stack traces,
private reasoning, or unnecessary raw model responses.

LangGraph remains out of scope because this is one linear, bounded operation
with no branching, pause, human resumption, or durable multi-node state.

## Alternatives

- Combining retrieval and the LLM adapter was rejected because it would couple
  PostgreSQL to one provider.
- Passing ORM objects or full prompt rows was rejected because it would make
  context unbounded and leak persistence concerns.
- Trusting model-authored provider/model or evidence IDs was rejected because
  structured syntax alone does not guarantee grounding.
- Holding one transaction across inference was rejected because local model
  latency would occupy a connection and snapshot unnecessarily.
- Unlimited retries or self-reflection were rejected because they behave like
  an unbounded workflow and obscure failure.
- A second LLM judge was deferred because it would add cost, circularity, and a
  second unvalidated model boundary.

## Consequences

The MVP obtains deterministic fake coverage and an opt-in real Ollama
acceptance test. A missing `qwen2.5:3b` model produces a clear skip or typed
provider error and never triggers a download.

Generation runs may remain `RUNNING` if PostgreSQL is unavailable when failure
recording is attempted; the original error is preserved. A future recovery job
may reconcile stale runs. Evidence can also change after it is read, but the
bounded evidence snapshot persisted with the run records what the provider
actually saw.

The fourteen-brief benchmark measures schema, grounding, constraint coverage,
review decisions, no-evidence behavior, persistence, repair attempts, and
latency. It does not prove that a prompt is creatively strong, factually
correct, or visually effective. Those properties still need representative
real data and human review.

The final local hardening run labeled `Qwen 2.5 3B local, synthetic dataset of
14 briefs` completed 14/14 cases. Schema validity, constraint accounting,
constraint coverage, no-evidence handling, rejected-warning citation, and run
persistence were 100%; no evidence or constraint IDs were fabricated.
Positive-evidence citation was 100%, no repair was used, confidence averaged
0.5998 (range 0.10-0.8589), and latency was 8,247 ms p50 and 8,779.45 ms p95.

The original exhausted-repair pattern was a missing citation followed by an
empty rationale. The explicit wire rationale removed that structural failure.
A final delivery audit also found that the degradable missing-citation check
could precede a hard covered/unmet overlap. Hard invariants now run first, and
the single wire accounting map makes overlap impossible. The final Qwen run
completed with 100% positive citation and zero repairs. The deterministic fake
provider completed 14/14 with all rates at 100%, zero repairs, confidence
averaging 0.6940 (range 0.25-0.82), and 257/2,095.75 ms p50/p95; its p95
includes one 5,479 ms embedding outlier. These figures expose model and runtime
variability rather than claiming universal quality.
