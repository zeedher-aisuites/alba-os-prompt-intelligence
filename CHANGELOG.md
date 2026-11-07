# Changelog

All notable changes to Alba OS Prompt Intelligence are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0-demo] — 2026-11-07 (experimental branch `experimental/demo-close`)

Closed as a usable, transferable local demo. No new product features were
added; the scope is frozen at Stage 5 plus the demo-close work below.
This release was prepared locally only and has not been pushed to GitHub.

### Added

- One-command demo startup: `scripts/demo.sh` (Linux/macOS) and
  `scripts/demo.ps1` (Windows/PowerShell). They check prerequisites, start
  PostgreSQL, apply Alembic migrations, set up durable workflow checkpoints,
  seed demo data idempotently, rebuild embeddings, and start the web
  interface on `127.0.0.1:8000`. Fake mode is the default and needs no
  Ollama models; `--ollama` mode verifies that `embeddinggemma:300m` and
  `qwen2.5:3b` are already installed and never downloads them.
- Three one-click demo briefs on the workflow creation form, reusing seeded
  projects: approve (cobalt host, retrieval-evaluation-lab), revise
  (station frames, retrieval-evaluation-lab), and reject (logo, Cobalt
  Lounge, which has no logo examples, so no approved evidence is retrieved).
- Minimal CSV corpus importer: `scripts/import_prompt_corpus.py`. It reuses
  the existing prompt-corpus-v1 validator, requires an existing project,
  and is idempotent by project plus prompt and by the `external-id:<id>`
  tag it records. `source_reference` and `created_at` have no storage
  column and are reported as not stored. Imported examples have no
  embedding until `rebuild_embeddings` runs. Documented in
  `docs/data/prompt-corpus-v1.md`.
- MIT `LICENSE` (Copyright 2026 José Eduardo Hernández).
- Foolproof getting-started guide: `docs/getting-started.md`. It is
  written for first-time users with no programming experience: what
  Alba does in plain words, official install links and checks for Git,
  uv, Docker Desktop, and Ollama, numbered steps from opening
  PowerShell to the three demo briefs, the Windows ExecutionPolicy
  workaround, real-model mode, CSV import, stop/reset/uninstall, a
  troubleshooting table, and a glossary. The README now points to it
  first and links the official install pages.
- Demo-first README: 5-minute quickstart, the three demo cases, fake vs
  real-model modes, CSV import, what the demo does not do, and reset
  instructions (`docker compose down --volumes`).

### Changed

- Fake workflows are now self-contained: the workflow factory pairs the
  embedding provider with the recommendation provider, and the web
  readiness gate only requires EmbeddingGemma for `ollama` workflows.
  Previously a `fake` workflow still required Ollama for retrieval
  embeddings, so a model-free demo was impossible. Fake embeddings and
  recommendations remain diagnostic only and must never be reported as
  EmbeddingGemma or Qwen quality.
- README requirements now state that Ollama is only needed for `--ollama`
  mode, and the library section points to the CLI importer instead of
  calling the CSV template “not an automatic importer”.

### Not included (out of scope for this demo)

Authentication, CSRF protection, TLS, multi-user support, public
deployment, image generation or analysis, ANN index, chunking, reranking,
hybrid search, multi-agent behavior, streaming, and telemetry.

### Verification (Linux VM, 2026-11-07)

- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — passed.
- `uv run pyright` — 0 errors, 0 warnings.
- `uv run pytest tests/unit` — 127 passed (main baseline: 121; the 6 new
  tests are the importer mapping tests and the workflow-factory wiring test).
- `uv run pytest` (default markers) — 127 passed, 50 errors. All 50 errors
  are integration-test fixture failures with `ConnectionRefusedError` to
  PostgreSQL on `127.0.0.1:5432`; no PostgreSQL was available in this VM.
  The same 50 errors occur on clean `main` (121 passed there), so no new
  failure was introduced.
- `bash -n scripts/demo.sh` — passed. `scripts/demo.sh --help` — passed.
- `node --check app/web/static/js/app.js` — passed.
- `workflows/new.html` renders with Jinja2 and contains all three demo
  buttons and the seeded project slugs — passed.
- `scripts/demo.ps1` — no PowerShell parser was available in this VM, so
  it was reviewed manually and checked for balanced braces, parentheses,
  and brackets only. It must be run on Windows before the demo is trusted.

### Not verified here

Full demo startup with Docker/Postgres/Ollama, the three demo briefs
end to end in a browser, `--ollama` mode, and the PowerShell script on
Windows. Test those on the target machine with `.\scripts\demo.ps1`
before publishing this branch.
