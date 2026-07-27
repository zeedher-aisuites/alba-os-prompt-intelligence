# Prompt corpus v1 contract

This CSV is a user-owned preparation format for the read-only Alba OS library.
It is deliberately **not** an import format yet: the PostgreSQL schema has no
stable external identity or provenance columns, so automatic import would not
be safely idempotent. Validation never writes PostgreSQL, generates embeddings,
or edits the CSV.

Start from `data/templates/prompt-corpus-v1.csv`, save as UTF-8 CSV, then run:

```powershell
uv run python -m scripts.validate_prompt_corpus path\to\my-corpus.csv --strict
```

The command writes a JSON report to standard output. A non-zero exit code means
there are validation errors (or, with `--strict`, warnings that need review).
Keep real corpus files outside Git unless explicitly approved for the project.

| Column | Required | Contract |
| --- | --- | --- |
| `external_id` | yes | Your stable identifier, 1–120 characters, unique in the CSV. It is not stored in PostgreSQL yet. |
| `project_slug` | yes | Existing or planned project identifier in lowercase kebab-case, up to 120 characters. |
| `query_type` | yes | One of `ai_influencer`, `toon`, `product_brand`, `marketing`, `logo`, `video_frame`, `art`, `other`. |
| `prompt` | yes | Source prompt, 1–16,000 characters. Maps conceptually to `PromptExample.base_prompt`. |
| `expected_result` | yes | Intended outcome, 1–16,000 characters. |
| `result_description` | no | Description of the observed result, up to 12,000 characters. |
| `status` | yes | `approved`, `in_review`, or `rejected`. |
| `rejection_reason` | no | Reason a rejected example should not become positive evidence, up to 2,000 characters. |
| `review_notes` | no | Human review context, up to 8,000 characters. |
| `platform` | yes | Generation service used for this experience, up to 100 characters; for example `openai`, `pixverse`, or `kling`. |
| `generation_method` | yes | How the result was generated, up to 100 characters; use a portable identifier such as `text-to-image`, `image-to-image`, `image-editing`, `text-to-video`, or `image-to-video`. |
| `tags` | yes | Pipe-separated (`|`) labels for strengths, failures, or recurring patterns. Each tag is up to 80 characters; whitespace and duplicates are normalized only in the report. |
| `source_reference` | no | Your source reference, up to 1,000 characters. It is not stored in PostgreSQL yet. |
| `created_at` | no | ISO-8601 timestamp with timezone, for example `2026-01-01T12:00:00Z`. |

The validator detects duplicate `external_id` values and duplicate normalized
rows. It does not verify that `project_slug` already exists in Alba OS because
that would couple spreadsheet preparation to a development database.

## Library filter vocabulary

`project_slug` identifies the workstream that owns an experience. `query_type`
describes the creative category. `platform` identifies the generation service,
and `generation_method` describes the input-to-output mode; neither replaces the
other. `tags` are short, repeatable labels for patterns in the result or review.

Use lower-case, portable values when preparing a new corpus. The read-only
library compares platform and tags case-insensitively after trimming whitespace.
For tags and generation methods, it also treats underscores, hyphens, and
repeated whitespace as the same display/filter value. Those rules affect
library filtering only; they do not rewrite persisted rows or CSV input silently.

For example:

```text
platform = openai
generation_method = image-to-image
tags = identity-preservation|cobalt|negative-space
```

The CSV separator for tags is always `|`, not commas. A tag is matched exactly
in the library, so `cobalt` does not also match `cobaltx`.
