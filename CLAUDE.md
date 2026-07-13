# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Lectora Backend** is a FastAPI backend for AI-assisted course generation. It ingests DOCX/PDF source documents, generates a timed outline, learning objectives, and full course content via Azure OpenAI, validates content against rule packs, and renders a final DOCX study guide.

**Stack**: FastAPI + Uvicorn · Azure SQL (or SQLite locally) · SQLAlchemy + Alembic · Microsoft Semantic Kernel · Azure Blob Storage · Azure Service Bus · Azure AI Search · Langfuse tracing

## Commands

```bash
# Activate venv (repo ships with venv/ at root)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run migrations then start API (seed_lookup_tables runs automatically on startup)
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

No test suite exists yet.

## Authentication

All API endpoints except `GET /health` require a **Microsoft Entra ID (Azure AD) Bearer token**.

- **FastAPI dependency**: `require_valid_token` in `app/core/auth/dependencies.py` — applied at router level via `dependencies=[Depends(require_valid_token)]`
- **Validation**: RS256 JWT against Microsoft JWKS (1-hour in-process cache); checks signature, expiry, audience, issuer, tenant (`tid`), and required scope (`scp`)
- Raises `HTTP 401` on any failure; detail is always `"Unauthorized"` (no leak of reason)

Required env vars (`AuthSettings` in `app/core/auth/config.py`):
```
AZURE_TENANT_ID, AZURE_API_CLIENT_ID, AZURE_API_AUDIENCE,
AZURE_API_SCOPE (optional, defaults to "access_as_user"),
AZURE_AUTHORITY, AZURE_JWKS_URL, AZURE_ISSUER
```

## Architecture

### Directory Layout

```
app/
  api/v1/endpoints/
    onboarding/          CRUD routers (course_basic, course_run, course_run_spec, etc.)
    content_generation/  Job lifecycle routers (create, poll, SSE stream, cancel)
    health.py            Unauthenticated health probe
    storage.py           Blob upload endpoint
  core/
    config.py            All Pydantic settings (AzureSQLSettings, LLMPipelineSettings, etc.)
    auth/                Entra ID token validation (config, dependencies, token_validator)
    service_bus/         Service Bus publisher, consumer, worker (background thread), message models
    storage/             Azure Blob Storage client
  db/
    session.py           AzureDatabaseClient + get_db() dependency
    migrations/          Alembic migrations
    seed_lookups.py      Seeds job-status lookup table on startup (idempotent)
  kernel/
    factory.py           Kernel init: AzureChatCompletion + AzureAISearchStore
    chat.py              LLM chat helpers (chat / chat_async, tracing, JSON enforcement)
    model_registry.py    Per-agent deployment map; overrides persist to model_overrides.json
  models/
    onboarding/          CourseBasic, CourseRun, CourseRunSpec, CourseRunInput, etc.
    course_generation/   CourseGenerationJob, JobArtifact, JobStatus, ValidationRun
  orchestrators/         High-level generation workflows (one per pipeline stage)
  services/
    onboarding/          CRUD + business logic per resource
    onboarding/course_generation/  Job lifecycle services (job_service, pipeline_runner,
                                   data_loader, artifact_service, job_progress_service)
  repositories/          SQLAlchemy query layer; services call repos, not ORM directly
  schemas/               Pydantic request/response schemas
  ai/
    agents/
      to_generation_pipeline/      4-step TO generation pipeline
      content_generation_agent/
        section_mapper/            Maps outline → spec + optional AI Search retrieval
        content_writer_agent/      Generates lesson content + renders DOCX
        content_validation/        Deterministic + AI validation checks
        content_refine_agent/      LLM repair for failing sections
    rule_pack_config/    Rule pack resolution (word counts, tone, tolerance)
    shared_utils/        Shared utilities (course-id, outline cleanup, etc.)
    ingestion/           Document chunking + embedding pipeline
```

### End-to-End Job Flow

```
POST /course-runs/{id}/jobs
  │
  ├─ (optional) Validate + enrich training_outline via TO Step 04 synchronously
  ├─ Persist CourseGenerationJob (status=PENDING)
  └─ Publish {job_id, course_run_id} to Service Bus
         │
         ▼
  CourseGenerationWorker (daemon thread, started at app lifespan)
         │
         ▼
  CourseGenerationPipelineRunner.run()
    ├─ Mark job PROCESSING
    ├─ CourseGenerationDataLoader — load course spec, resolve blob paths
    ├─ ContentGenerationOrchestrator.execute()
    │    ├─ SECTION_MAPPER: map outline to spec + AI Search enrichment
    │    ├─ A2: per-lesson LLM content generation
    │    ├─ S2: deterministic + AI validation, repair loop (≤2 attempts)
    │    └─ A6: render study_guide.docx
    ├─ Persist artifacts to blob (pipeline_input.json, enriched_sections.json,
    │   study_guide.docx, validation_report.json)
    └─ Mark job COMPLETED / FAILED
```

Each pipeline stage transition is committed immediately so a concurrent SSE poller sees progress in real time.

### Job Lifecycle APIs

All endpoints require Bearer auth.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/course-runs/{id}/jobs` | Queue a generation job (body: `requested_by`, optional `training_outline`) |
| `GET` | `/jobs/{job_id}` | REST snapshot: status + per-stage progress |
| `GET` | `/jobs/{job_id}/events` | SSE stream: live stage/log updates, `done` on terminal, `timeout` at 30 min |
| `DELETE` | `/jobs/{job_id}` | Cancel a PENDING or PROCESSING job |

**SSE implementation note**: Each poll opens its own short-lived DB session (not the request-scoped one) because pyodbc connections must not be shared across threads. `X-Accel-Buffering: no` is set to prevent nginx/Azure Front Door from buffering frames.

### Job Stages (match frontend `backendId` values exactly)

| Code | Frontend label | Notes |
|---|---|---|
| `SECTION_MAPPER` | Section Mapper | Map outline to source content |
| `A2` | Content Generation | Per-lesson LLM writer |
| `S2` | Validation | Validate + repair loop |
| `A6` | Assembly | Render study_guide.docx |

`A1` (Step 04 outline enrichment) runs synchronously inside `job_service.create_and_queue()` before the job is queued — it is intentionally not shown on the frontend stage tracker.

### Data Model

```
CourseBasic (identity)
  └── CourseRun (versioned generation attempt)
        ├── CourseRunSpec       (duration, difficulty, audience, tone, rule family)
        ├── CourseRunInput      (references to uploaded DOCX/PDF files)
        └── CourseRunRuleOverride

CourseGenerationJob  (linked to CourseRun)
  ├── CourseGenerationJobArtifact  (blob paths: study guide, validation report, etc.)
  └── CourseGenerationValidationRun  (S2 pass/fail per attempt)
```

`CourseGenerationJobStatus` is a lookup table seeded automatically on startup via `seed_lookup_tables()`.

### Timed Outline (TO) Generation Pipeline (`app/ai/agents/to_generation_pipeline/`)

The TO agent is a 4-step sub-pipeline:

| Step | Purpose |
|---|---|
| `step_01_parse_and_generate_outline/` | Classify input, parse source docs, generate draft outline (phases: classification → parse → to_generation → finalization) |
| `step_02_validate_outline/` | Validate structure and rule-pack constraints, write report |
| `step_03_repair_outline/` | LLM repair of validation failures, persist corrected outline |
| `step_04_enrich_outline/` | Enrich outline metadata (8 phases, managed via shared-state loader/writer) |

### LLM / Kernel

- `app/kernel/model_registry.py` maps agent IDs (`A0`, `A0_TO`, `A1`, `A2`) to Azure OpenAI deployments; overrides persist to `model_overrides.json` and take effect on next call (no restart)
- `chat()` / `chat_async()` in `app/kernel/chat.py` wrap all LLM calls with tracing (Langfuse → local JSONL fallback)

### Key Patterns

- **Graceful degradation**: AI Search missing → `matched_chunks=None`; Langfuse missing → JSONL fallback; Service Bus not configured → worker silently skips startup
- **Idempotency guard**: `CourseGenerationPipelineRunner.run()` checks for terminal status first — redelivered Service Bus messages never re-run a finished job
- **Service-Bus-free runner**: `CourseGenerationPipelineRunner` has no Service Bus import; callable from tests or scripts directly
- **Per-commit SSE visibility**: every stage transition and activity log is committed (not just flushed) immediately so the SSE endpoint sees it from a separate DB session
- **Runtime LLM swap**: `set_deployment(agent_id, deployment)` updates `model_overrides.json`; no restart needed

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
| Service Bus | `SERVICE_BUS_CONNECTION_STRING`, `QUEUE_NAME` | Job queue (worker skips if unset) |

**Local dev**: `DATABASE_URL=sqlite:////absolute/path/to/db.sqlite` · `LOG_LEVEL=DEBUG` · `SQL_ECHO=true`

## Known Gaps

- **Topic Outline Orchestrator** (`app/orchestrators/topic_outline/`) has leftover imports from a removed `lectora_backend` package — needs migration to `app/ai/shared_utils/`.
- **Rule packs** (`app/ai/rule_pack_config/`) are generic placeholders; actual business rules not yet populated.
- **Legacy pipeline** (`app/pipeline/agents/content_generation_agent/pipeline.py`, `lesson_gate.py`) is superseded by `ContentGenerationOrchestrator` and should be removed.

## Related Docs

- `WORKFLOW.md` — detailed pipeline architecture with mermaid diagrams
- `.env.example` — full environment variable reference with inline notes
