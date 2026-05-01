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
- **PII scrubbing is mandatory**: All resume text must pass through GLiNER before any LLM call. Raw PII is stored only in designated fields — never logged or forwarded to the LLM.
- **Resume Summary is cached**: Redis key `summary:{candidate_id}:{jd_id}`, TTL 24 hours (configurable via `SUMMARY_CACHE_TTL`).
- **JD refinements are capped**: 6 refinements per session. A `429` with `REFINEMENT_LIMIT_REACHED` is returned when the cap is hit.
- **Contact Draft has no refinement cap**: Users may refine a draft unlimited times within a session.

---

## Session Persistence Pattern

Features with multi-turn LLM interaction (JD Creator, Contact Draft) follow this pattern. Apply it to any future feature that needs iterative refinement.

### Request contract
- `session_id: uuid.UUID` — **always provided by the client**, never generated server-side.
- `input_type: Optional[List[Literal[...]]]` — declares which content fields the client is sending.
- Content fields (`raw_text`, `template`, `details`, etc.) — validator raises `ValueError` only when **all** content fields are absent.

### Server-side dispatch
The endpoint looks up `session_id` in PostgreSQL on every call:
- **No row found** → initial generation. Create the session record after streaming completes.
- **Row found** → refinement turn. Load message history, call LLM, update the record.

```python
async with async_session_factory() as db:
    result = await db.execute(select(XSession).where(XSession.id == request.session_id))
    session = result.scalar_one_or_none()

if session is None:
    return await self._generate(request)
return await self._refine(request, session)
```

### Streaming + DB write
Buffer the full LLM response while streaming, then write to DB **after the stream ends** inside the generator:

```python
async def stream() -> AsyncGenerator[str, None]:
    collected: list[str] = []
    async for chunk in llm.astream(lc_messages):
        if chunk.content:
            collected.append(chunk.content)
            yield f"event: content\ndata: {json.dumps(chunk.content)}\n\n"

    ai_text = "".join(collected)
    # persist to DB here
    yield f"event: metadata\ndata: {json.dumps(metadata)}\n\n"
    yield "event: complete\ndata: [DONE]\n\n"
```

### Message history
- Stored as a JSON array in the session table: `[{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]`
- **System prompt is never stored** — it is injected fresh from the prompt file on every call.
- On refinement, the full history is reconstructed as LangChain `HumanMessage` / `AIMessage` objects and prepended with the appropriate system prompt.

### SSE event shape (all session-based endpoints)
```
event: content   → streamed LLM output chunks
event: metadata  → { session_id, <feature_id>, [refinements_remaining if capped] }
event: complete  → [DONE]
```

### DB table conventions
Each session-based feature has its own table in `app/core/database.py`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | = `session_id`, set by client |
| `<feature>_id` | UUID | Server-generated public identifier for the output |
| `<output_field>` | Text | Latest full LLM output (e.g. `jd_html`, `draft_json`) |
| `messages` | JSON | Conversation history (no system prompt) |
| `refinements_remaining` | Integer | Only for capped features (e.g. JD Creator) |
| `created_at` / `updated_at` | DateTime(tz) | Standard audit columns |

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
