# ADR 0001: PostgreSQL and pgvector as persistence

## Context

Alba OS needs durable relational data, transactional human review, structured
JSON payloads, and a semantic index that can be rebuilt from source records.
The first phase runs locally but must preserve a path to production.

## Decision

PostgreSQL is the source of truth and pgvector supplies a nullable
`vector(768)` column for a later derived semantic index. The dimension is an
explicit match for the planned EmbeddingGemma model's full output. Google also
supports smaller Matryoshka dimensions, but Alba OS chooses the full output
until retrieval evaluation provides evidence for a smaller representation.
[Google's EmbeddingGemma overview](https://ai.google.dev/gemma/docs/embeddinggemma)
documents the flexible 768-to-128 output range.
`app/db/constants.py` is the single runtime source for this schema value; an
Alembic migration keeps its own literal as an immutable historical snapshot.
SQLAlchemy 2 is used asynchronously with asyncpg, and Alembic owns schema
evolution.

Application enums are stored as `VARCHAR` values protected by named `CHECK`
constraints. This keeps migrations transactional and makes vocabulary changes
more direct than PostgreSQL native enum alterations.

Tags, human-review lists, provider parameters, and recommendation payloads use
JSONB because their elements have no independent identity or lifecycle in this
phase. Projects, examples, reviews, and runs remain normalized tables.

Project deletion is restricted while examples or runs exist. Human reviews are
deleted with their prompt example because they cannot exist independently.
Relationships use `lazy="raise"` so async code must request related data
explicitly rather than triggering hidden database I/O.

The initial upgrade enables `vector` with `CREATE EXTENSION IF NOT EXISTS`.
Downgrade removes Alba tables but deliberately retains the extension because
another schema or application in the same database may depend on it.

## Alternatives

- SQLite was rejected because it cannot verify PostgreSQL, JSONB, asyncpg, or
  pgvector behavior.
- A separate vector database was rejected because it would add another source
  of truth and operational complexity.
- Native PostgreSQL enums were rejected for this MVP because adding or changing
  values has more migration constraints.
- Fully normalized tag and review-list tables were deferred because those
  values do not yet need independent queries or ownership.

## Consequences

Integration tests require a real PostgreSQL/pgvector service. JSONB structures
must still be validated at application boundaries. Enum changes require matching
Python and database-constraint migrations.

The fixed vector dimension requires a migration if the future embedding model
uses a different dimension. While Stage 1 contains only `NULL` vectors, that
migration could alter the column directly. Once embeddings or ANN indexes exist,
the safe procedure is:

1. add a new nullable `vector(new_dimension)` column;
2. regenerate every vector from source `embedding_text`;
3. build a new HNSW or IVFFlat index on the new column;
4. switch retrieval after validating the rebuilt index;
5. drop the old index and column in a later migration.

Existing vectors cannot be padded or truncated blindly unless the model
explicitly guarantees compatible Matryoshka representations. Switching models
requires regeneration. An exclusive Alba database may drop the retained
extension manually after downgrade. A shared database must preserve it.

The vector column remains nullable and no embedding or vector index is generated
in Stage 1.
