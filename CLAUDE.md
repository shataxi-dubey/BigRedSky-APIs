# CLAUDE.md

## Project

Applicant Tracking System (ATS) — Python/FastAPI backend API suite with five features: Resume Parser, JD Creator, Resume Summary, Contact Draft, and AI Ranking. See `PRD.md` for full specs and working requirements summary.

---

  ## Pre-Implementation Checklist

  Before writing any code for a feature:
  1. **Read `PRD.md`** — understand the exact endpoints, request/response schemas, and pipeline steps defined for the feature.
  2. **Read `rule.md`** — confirm folder structure and naming conventions.
  3. Only then ask clarifying questions about decisions the PRD leaves open.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | FastAPI (class-based views via `fastapi-utils` `@cbv`) |
| Task queue | Celery + Redis |
| Cache | Redis (`aiocache`) |
| LLM orchestration | LangGraph + LangChain |
| Embeddings | `sentence-transformers` (dense), BM25 (sparse) |
| Vector store | Qdrant (self-hosted) |
| PII scrubbing | Nvidia GLiNER |
| File parsing | PyMuPDF (PDF), python-docx (DOCX) |
| Auth | JWT (RS256) / OAuth 2.0 |
| Observability | Prometheus, Langfuse, Loguru |
| Python version | ≥ 3.9 |

---

## Package Management

Always use `uv` — never `pip`.

```bash
uv add <package>        # add dependency
uv remove <package>     # remove dependency
uv run <command>        # run in project environment
```

---

## Running the App

```bash
make run      # dev server with --reload
make start    # production server
make format   # black + isort
make lint     # ruff + mypy
make check    # pre-commit on all files
make test     # run tests
make clean    # remove __pycache__, .pytest_cache etc.
```

The app reads config from `.env`. Copy `docs/example.env` to `.env` to get started.

---

## Directory Structure

Defined in full in `rule.md`. Key rules:

- **Do not create any new folders.** All code goes into existing directories.
- Feature code lives under `app/apis/v1/{feature}/` with exactly these files: `__init__.py`, `controller.py`, `models.py`, `service.py` (add `helper.py` only when needed).
- Celery tasks live under `app/tasks/{feature}/`.
- LangGraph graphs live under `app/workflows/graphs/{feature}/`.
- Shared infrastructure (config, cache, exceptions, middleware, responses) lives in `app/core/` — never duplicated per feature.
- Constants and messages live in `app/constants/` — never hardcoded inline.

**ATS feature → folder mapping:**

| Feature | API | Tasks | Graph |
|---|---|---|---|
| Resume Parser & Summary | `app/apis/v1/resume/` | `app/tasks/resume/` | `app/workflows/graphs/resume/` |
| JD Creator | `app/apis/v1/jd/` | — | `app/workflows/graphs/jd/` |
| Resume Summary | `app/apis/v1/resume/` | — | `app/workflows/graphs/summary/` |
| Contact Draft | `app/apis/v1/contact/` | — (sync) | `app/workflows/graphs/contact/` |
| AI Ranking | `app/apis/v1/ranking/` | `app/tasks/ranking/` | `app/workflows/graphs/ranking/` |

---

## Code Conventions

### Controllers (`controller.py`)
- Use class-based views: `@cbv(router)` from `fastapi_utils.cbv`.
- Endpoint methods call `self.service.*` — no business logic inline.
- Return `AppJSONResponse` or `AppStreamingResponse` from `app.core.responses`.

### Services (`service.py`)
- All business logic lives here.
- Call LangGraph graphs or Celery tasks — do not inline LLM calls directly.

### Models (`models.py`)
- Pydantic v2 request and response schemas only.
- No logic, no DB calls.

### Tasks (`{feature}_task.py`)
- Decorate with `@celery_app.task` from `app/tasks/celery_main.py`.
- Keep tasks idempotent — they must be safe to retry.

### Config
- All settings are Pydantic `BaseSettings` in `app/core/config.py`, loaded from `.env`.
- Access via the `settings` singleton — never use `os.environ` directly.

### Error handling
- Raise exceptions from `app/core/exceptions/base.py`.
- Global handlers are registered in `app/core/exceptions/handle_exception.py`.
- All error responses follow the envelope: `{ "error_code", "message", "details", "request_id" }`.

---

## Architecture Decisions

- **Async-first**: Long-running operations (resume chunking, AI ranking) return `202 + job_id` immediately; clients poll a status endpoint.
- **Contact Draft is synchronous**: Single LLM call, result returned directly. No Celery task, no polling.
- **PII scrubbing is mandatory**: All resume text must pass through GLiNER before any LLM call. Raw PII is stored only in designated fields — never logged or forwarded to the LLM.
- **Resume Summary is cached**: Redis key `summary:{candidate_id}:{jd_id}`, TTL 24 hours (configurable via `SUMMARY_CACHE_TTL`).
- **JD refinements are capped**: 5 refinements per session. A `429` with `REFINEMENT_LIMIT_REACHED` is returned when the cap is hit.

---

## Git Workflow

- `main` — stable, production-ready code. Never commit directly to this branch.
- `development` — integration branch. Never commit directly to this branch.
- **Every new feature must be developed on a dedicated branch created from `development`:**

```bash
git checkout development
git pull origin development
git checkout -b feature/<feature-name>
```

- Branch naming: `feature/<feature-name>` (e.g. `feature/resume-parser`, `feature/ai-ranking`).
- Open a PR targeting `development` when the feature is complete. Merge to `main` only via a release PR from `development`.
