# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Lectora Backend** is a FastAPI backend for AI-assisted course generation. It ingests DOCX/PDF source documents, generates a timed outline, learning objectives, and full course content via Azure OpenAI, validates content against rule packs, and renders a final DOCX study guide.

**Stack**: FastAPI + Uvicorn · Azure SQL (or SQLite locally) · SQLAlchemy + Alembic · Microsoft Semantic Kernel · Azure Blob Storage · Azure AI Search · Langfuse tracing

## Commands

```bash
# Activate venv (repo ships with venv/ at root)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run migrations then start API
alembic upgrade head
uvicorn app.main:app --reload          # dev (localhost:8000)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4  # prod

# Alembic migration operations
alembic revision --autogenerate -m "Description"
alembic downgrade -1
alembic current

# Health check
curl http://localhost:8000/health
# Interactive docs
open http://localhost:8000/docs
```

No test suite exists yet (to be added: unit tests for services/repositories, integration tests for orchestrators, endpoint tests).

## Architecture

### Directory Layout

```
app/
  api/v1/endpoints/      FastAPI routers (onboarding CRUD, health, storage)
  core/config.py         All Pydantic settings objects (AzureSQLSettings, LLMPipelineSettings, etc.)
  db/session.py          AzureDatabaseClient + get_db() FastAPI dependency
  db/migrations/         Alembic migrations
  kernel/
    factory.py           Kernel init: registers AzureChatCompletion + AzureAISearchStore
    chat.py              LLM chat helpers (chat / chat_async, tracing, JSON enforcement)
    model_registry.py    Per-agent deployment mapping; overrides persisted to model_overrides.json
  models/onboarding/     SQLAlchemy ORM models
  orchestrators/         High-level generation workflows (one per pipeline stage)
  services/onboarding/   Business logic + validation (one service per resource)
  repositories/          SQLAlchemy query layer (services call repos, not ORM directly)
  schemas/               Pydantic request/response schemas
  core/auth/
    config.py            AuthSettings (Azure AD / Entra ID settings)
    dependencies.py      require_valid_token FastAPI dependency
    token_validator.py   RS256 JWT validation against Microsoft JWKS (1-hr cache)
  ai/
    agents/              LLM-driven agents
      to_generation_pipeline/      4-step TO generation pipeline (see below)
      content_generation_agent/
        section_mapper/            Maps timed-outline lessons to spec + vector retrieval
        content_writer_agent/      Generates lesson content + renders DOCX
        content_validation/        Deterministic + AI validation
        content_refine_agent/      LLM repair for failing sections
    rule_pack_config/    Rule pack resolution (word counts, tone, tolerance)
    shared_utils/        Shared utilities (course-id, outline cleanup, etc.)
    ingestion/           Document chunking + embedding pipeline
```

### Data Model

```
CourseBasic (identity)
  └── CourseRun (versioned generation attempt)
        ├── CourseRunSpec   (duration, difficulty, audience, tone, rule family)
        ├── CourseRunInput  (references to uploaded DOCX/PDF files)
        └── CourseRunRuleOverride (optional per-run rule-pack overrides)
```

### Content Generation Pipeline

```
Source Docs → Timed Outline (A0_TO) → Learning Objectives (A1) → Content (A2) → study_guide.docx
```

Each orchestrator follows **Generate → Validate → Refine → Validate** (capped at ~2 repair attempts). `ContentGenerationOrchestrator` is fully in-memory (no shared-state file):
1. `SectionMapper` — maps TO lessons to course spec, optionally enriches with AI Search chunks
2. `content_generation_agent` (A2) — per-lesson LLM calls
3. `content_validation` — deterministic (word counts, forbidden phrases) + AI semantic checks
4. `content_refine_agent` — LLM repair if blockers found
5. Render `study_guide.docx`

#### Timed Outline (TO) Generation Pipeline (`app/ai/agents/to_generation_pipeline/`)

The TO agent is itself a 4-step pipeline:

| Step | Directory | Purpose |
|---|---|---|
| 1 | `step_01_parse_and_generate_outline/` | Classify input, parse source docs, generate draft outline (phases: classification → parse → to_generation → finalization) |
| 2 | `step_02_validate_outline/` | Validate outline structure and rule-pack constraints, write validation report |
| 3 | `step_03_repair_outline/` | LLM-based repair of validation failures, persists corrected outline |
| 4 | `step_04_enrich_outline/` | Enrich outline with additional metadata (8 phases, managed via shared state loader/writer) |

### LLM / Kernel

- `app/kernel/factory.py` builds a `semantic_kernel.Kernel` with Azure OpenAI services registered
- `app/kernel/model_registry.py` maps agent IDs (`A0`, `A0_TO`, `A1`, `A2`) to deployments; overrides persist to `model_overrides.json` and take effect immediately (no restart)
- `chat()` / `chat_async()` in `app/kernel/chat.py` wrap all LLM calls with tracing (Langfuse → local JSONL fallback)

### Key Patterns

- **Graceful degradation**: Azure AI Search missing → sections get `matched_chunks=None`; Langfuse missing → local JSONL fallback; rule pack not found → defaults apply
- **Dependency injection**: `get_db()` yields session, `get_kernel()` yields Kernel instance, injected into endpoint handlers
- **Runtime LLM swap**: per-agent deployment overridable via `set_deployment()` and JSON file — useful for A/B testing without restart

## Authentication

All API endpoints except `GET /health` require a **Microsoft Entra ID (Azure AD) Bearer token**.

- **FastAPI dependency**: `require_valid_token` from `app/core/auth/dependencies.py` — applied at the router level via `dependencies=[Depends(require_valid_token)]`
- **Validation**: RS256 JWT validated against Microsoft JWKS endpoint (1-hour in-process cache); checks signature, expiry, audience, issuer, tenant (`tid`), and required scope (`scp`)
- **Token type**: access tokens only (`token_use == "id"` is rejected)
- Raises `HTTP 401` on any failure; error detail is always `"Unauthorized"` (no leak of reason)

Required env vars for auth (`AuthSettings` in `app/core/auth/config.py`):

```
AZURE_TENANT_ID, AZURE_API_CLIENT_ID, AZURE_API_AUDIENCE,
AZURE_API_SCOPE (optional, defaults to "access_as_user"),
AZURE_AUTHORITY, AZURE_JWKS_URL, AZURE_ISSUER
```

## Configuration

All config is `.env`-driven via Pydantic `BaseSettings`. Copy `.env.example` to `.env`.

| Group | Key vars | Required for |
|---|---|---|
| Database | `AZURE_SQL_*` or `DATABASE_URL` | Always |
| Auth | `AZURE_TENANT_ID`, `AZURE_API_CLIENT_ID`, `AZURE_API_AUDIENCE`, `AZURE_AUTHORITY`, `AZURE_JWKS_URL`, `AZURE_ISSUER` | All protected endpoints |
| LLM | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT` | Content generation |
| Vector Search | `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_API_KEY`, `AZURE_SEARCH_INDEX_NAME` | Section Mapper |
| Embeddings | `AZURE_OPENAI_EMBEDDINGS_RESOURCE_NAME`, `INGESTION_EMBEDDING_DEPLOYMENT` | Ingestion |
| Tracing | `LANGFUSE_*` | Optional (JSONL fallback) |
| Blob Storage | `AZURE_STORAGE_CONNECTION_STRING`, `BLOB_CONTAINER_NAME` | Artifact uploads |

**Local dev**: `DATABASE_URL=sqlite:////absolute/path/to/db.sqlite` · `LOG_LEVEL=DEBUG` · `SQL_ECHO=true`

## Known Gaps

- **API ↔ Pipeline not wired**: Onboarding endpoints persist metadata, but there is no endpoint that triggers the generation orchestrators. The intended path is a Service Bus job queue + worker that calls `ContentGenerationOrchestrator`.
- **Topic Outline Orchestrator** (`app/orchestrators/topic_outline/`) has leftover imports from a removed `lectora_backend` package — needs migration to `app/ai/shared_utils/`.
- **Rule packs** (`app/ai/rule_pack_config/`) are generic placeholders; actual business rules not yet populated.
- **Legacy pipeline** (`app/pipeline/agents/content_generation_agent/pipeline.py`, `lesson_gate.py`) is superseded by `ContentGenerationOrchestrator` and should be removed.

## Related Docs

- `WORKFLOW.md` — detailed pipeline architecture with mermaid diagrams
- `.env.example` — full environment variable reference with inline notes
