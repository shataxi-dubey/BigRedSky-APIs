# Directory Structure Rules

All new code must be placed in an existing folder. **Do not create any new top-level or second-level directories.**

---

## Top-Level Layout

```
bigredsky/
├── app/                    # All application source code
├── docker/                 # Docker service config files (prometheus, promtail)
├── docs/                   # Documentation and example env files
├── tests/                  # All tests
├── main.py                 # Application entry point
├── Makefile
├── Dockerfile
├── Dockerfile.celery
├── docker-compose.yml
├── docker-compose-langfuse.yaml
├── pyproject.toml
└── rule.md
```

---

## `app/` — Source Code

### `app/apis/`

All HTTP endpoint code lives here, versioned under `v1/`.

```
app/apis/v1/{feature}/
├── __init__.py
├── controller.py   # FastAPI router — endpoint definitions only, no logic
├── models.py       # Pydantic request and response schemas
├── service.py      # Business logic called by the controller
└── helper.py       # Pure helper/utility functions (add only when needed)
```

**ATS features → their folder names:**

| Feature | Folder |
|---|---|
| Resume Parser & Summary | `app/apis/v1/resume/` |
| JD Creator | `app/apis/v1/jd/` |
| Contact Draft | `app/apis/v1/contact/` |
| AI Ranking | `app/apis/v1/ranking/` |

`app/apis/monitor/` holds health, metrics, and root endpoints — do not add feature code here.

---

### `app/tasks/`

Celery background task definitions, one sub-folder per feature.

```
app/tasks/{feature}/
├── __init__.py
└── {feature}_task.py   # @celery.task definitions
```

**ATS features → their folder names:**

| Feature | Folder |
|---|---|
| Resume chunking / parsing | `app/tasks/resume/` |
| AI Ranking scoring | `app/tasks/ranking/` |

Contact Draft does **not** have a tasks folder — it is a synchronous single LLM call with no background processing.

`app/tasks/celery_main.py` is the Celery app instance — do not duplicate it.

---

### `app/workflows/`

LangGraph graphs and pipeline orchestrators.

```
app/workflows/graphs/{feature}/
├── __init__.py
├── graph.py              # Graph assembly — adds nodes and edges
├── states.py             # TypedDict graph state definitions
├── model_map.py          # LLM model configuration map
├── local_model_client.py # Local model client (if applicable)
├── components/           # One file per graph node / step
│   ├── __init__.py
│   └── {step_name}.py
├── tools/                # LangChain tool wrappers
│   ├── __init__.py
│   └── {tool_name}.py
└── prompts/              # Prompt templates as .md files
    ├── __init__.py
    └── {prompt_name}.md

app/workflows/pipelines/
└── __init__.py           # Pipeline orchestrators that call graphs
```

**ATS features → their folder names:**

| Feature | Folder |
|---|---|
| Resume parsing / chunking | `app/workflows/graphs/resume/` |
| JD generation / refinement | `app/workflows/graphs/jd/` |
| Resume summary | `app/workflows/graphs/summary/` |
| Contact draft | `app/workflows/graphs/contact/` |
| AI Ranking | `app/workflows/graphs/ranking/` |

---

### `app/core/`

Shared infrastructure — do not put feature-specific logic here.

```
app/core/
├── config.py              # Pydantic settings loaded from env vars
├── lifespan.py            # FastAPI lifespan (startup / shutdown)
├── server.py              # FastAPI app factory and router registration
├── logging_utils.py       # Structured logging helpers
├── cache/
│   └── cache.py           # Redis client and cache helpers
├── exceptions/
│   ├── base.py            # Custom exception classes
│   └── handle_exception.py# Global exception handlers
├── middlewares/
│   ├── logging.py         # Request/response logging middleware
│   └── rate_limiter.py    # Rate limiting middleware
└── responses/
    ├── json_response.py   # Standard JSON response wrapper
    └── stream_response.py # SSE / streaming response wrapper
```

---

### `app/constants/`

App-wide string constants and messages only — no logic.

```
app/constants/
├── constants.py   # Enum values, magic strings, config keys
└── messages.py    # User-facing and log message strings
```

---

## `tests/`

One test file per API feature.

```
tests/
├── __init__.py
├── test_{feature}.py   # e.g. test_resume.py, test_jd.py
```

---

## `docs/`

Documentation and environment reference files only — no source code.

```
docs/
├── example.env          # Annotated sample env file
└── {topic}.md           # One doc per topic (cache, logging, etc.)
```

---

## `docker/`

Config files consumed by `docker-compose.yml` — no Python source here.

```
docker/
├── prometheus/
│   └── prometheus.yml
└── promtail/
    └── promtail-config.yml
```

---

## Package Management

- Always use **`uv`** to install packages — never `pip`.
- To add a dependency: `uv add <package>`
- To remove a dependency: `uv remove <package>`
- To run a command in the project environment: `uv run <command>`

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

---

## Rules Summary

1. Every new ATS feature gets exactly one folder each under `app/apis/v1/`, `app/tasks/`, and `app/workflows/graphs/`.
2. Each feature folder must contain `__init__.py`, `controller.py`, `models.py`, and `service.py`. Add `helper.py` only if pure helpers exist.
3. All Celery task definitions go in `app/tasks/{feature}/` — never inline in a controller or service.
4. All LLM prompt templates go in `app/workflows/graphs/{feature}/prompts/` as `.md` files.
5. Shared infrastructure (auth, cache, exceptions, middleware) goes in `app/core/` — never duplicated per feature.
6. Constants and messages go in `app/constants/` — never hardcoded inline across multiple files.
7. Tests go in `tests/` — never alongside source files.
8. Documentation goes in `docs/` — never in the root except `README.md` and `rule.md`.
9. **Do not create any folder not listed in this document.**
10. **Always use `uv` for package installation — never `pip`.**
11. **Every new feature must be developed on a `feature/<feature-name>` branch created from `development` — never commit feature work directly to `development` or `main`.**
