# Alba OS engineering rules

These rules apply to every change in this repository:

- FastAPI owns HTTP concerns and the local web application.
- LangGraph is reserved for stateful workflows with branching, review, or resumption.
- PostgreSQL is the source of truth.
- The pgvector index is derived and must remain rebuildable.
- External providers are accessed through project-owned adapter interfaces.
- Every LLM output crossing an application boundary is validated.
- Dependencies are not added without a documented reason.
- Tests are never weakened merely to make a change pass.
- Architectural changes are made explicitly and documented.
- Every material change includes proportionate tests.
- Images may be stored and displayed in phase 1, but are not analyzed or sent to a model.
- Private chain-of-thought is never stored or displayed.
- Before a stage is considered complete, run:
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run pyright`
  - `uv run pytest`

