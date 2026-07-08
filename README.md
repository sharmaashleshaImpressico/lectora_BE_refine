# Lectora Backend (refine)

FastAPI backend for AI-assisted course generation: takes source study-guide
documents (DOCX/PDF), generates a timed outline, learning objectives, and
full course content, validates the content against a rule pack, and renders
a study-guide `.docx`.

## Stack

- **API**: FastAPI + Uvicorn
- **DB**: Azure SQL (or local SQLite) via SQLAlchemy + Alembic migrations
- **LLM**: Azure OpenAI via [Semantic Kernel](https://github.com/microsoft/semantic-kernel) (`app/kernel/`)
- **Storage**: Azure Blob Storage (job artifacts) + Azure Service Bus (job queue)
- **Retrieval**: Azure AI Search (document ingestion / chunk retrieval)
- **Tracing**: Langfuse + local JSONL traces

## Project layout

```
app/
  api/            FastAPI routers and dependencies (app/api/v1/endpoints/...)
  core/           Settings/config (Azure SQL, Azure OpenAI, Langfuse, ...)
  db/             SQLAlchemy session + Alembic migrations
  kernel/         Semantic Kernel factory, chat helpers, model registry
  models/         SQLAlchemy models
  orchestrators/  High-level orchestrators (topic_outline, learning_objective,
                  required_topics, content_generation) built on app/kernel
  ai/             Pipeline agents and shared pipeline infrastructure
                  agents/            content_generation_agent, to_generation_pipeline,
                                     learning_objective_agent, required_topic
                  rule_pack_config/  rule-pack resolution (content generation + timed outline)
                  shared_llm_config/ back-compat shim onto app/kernel + tracer
                  shared_utils/      course-id resolution, outline cleanup, learning
                                     objectives, interactive elements, image validation
  repositories/   Data-access layer
  schemas/        Pydantic request/response schemas
  services/       Application services
```

## Getting started

1. **Python**: 3.11+ (a `venv/` is expected at the repo root; recreate with
   `python3 -m venv venv` if missing).
2. **Install dependencies**:
   ```bash
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Configure environment**: copy `.env.example` to `.env` and fill in the
   values you need (Azure SQL or a local SQLite `DATABASE_URL`, Azure OpenAI,
   Azure Storage/Service Bus, Azure AI Search, Langfuse). See `.env.example`
   for the full list and inline notes.
4. **Database migrations**:
   ```bash
   alembic upgrade head
   ```
5. **Run the API**:
   ```bash
   uvicorn app.main:app --reload
   ```
   The app initializes the DB schema on startup and exposes routes under
   `/health`, `/course-basic`, and `/course-run` (see `app/api/v1/api.py`).

## Configuration notes

- Minimum to boot: a working database connection (`AZURE_SQL_*` or
  `DATABASE_URL`) and `LOG_LEVEL`.
- LLM generation requires `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY`;
  per-agent model deployments are resolved dynamically via
  `app/kernel/model_registry.py` (overridable without a restart).
- Document ingestion/retrieval (Section Mapper's vector search) requires
  `AZURE_SEARCH_*` and the embeddings resource vars — without them, retrieval
  degrades gracefully (no matched source chunks) rather than failing.
- Content-generation rule packs (word-count targets, tone, error tolerance)
  currently ship as generic placeholders in `app/ai/rule_pack_config/`
  pending the real business rules.

## Known gaps

- `app.orchestrators.topic_outline` is mid-fix: `app/ai/agents/to_generation_pipeline/`
  still has a handful of leftover imports from the removed `lectora_backend`
  package (course-id resolution, outline cleanup, learning-objective
  normalization, and the timed-outline rule pack) that need native
  replacements under `app/ai/shared_utils/` and `app/ai/rule_pack_config/`.
- `app.orchestrators.content_generation`, `app.orchestrators.learning_objective`,
  and `app.orchestrators.required_topics` all import cleanly today. The old
  `content_generation_agent/pipeline.py` and `lesson_gate.py` (legacy,
  file-based `shared_state.json` code tied to a "central orchestrator"
  framework that no longer exists) have been removed — fully superseded by
  `app.orchestrators.content_generation.ContentGenerationOrchestrator`.
