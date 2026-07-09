# Cursor Skill: Generation Endpoint Builder

You are implementing a single AI generation endpoint in this FastAPI backend.

Follow the approved project flow:

Request flow:

```text
Endpoint → Service → Feature Orchestrator → Agents
```

Response flow:

```text
Agents → Feature Orchestrator → Service → Endpoint → Frontend
```

Do not create a competing pipeline, central orchestrator, hidden pipeline entrypoint, or agent registry unless explicitly requested.

## Task Scope

Implement only the requested generation endpoint.

Do not:

* Add unrelated APIs.
* Add regenerate/refine API unless explicitly requested.
* Add RAG unless explicitly requested.
* Add DB persistence unless explicitly requested.
* Add Service Bus/background jobs unless explicitly requested.
* Restructure large folders unnecessarily.

## Required Implementation Steps

### 1. Confirm route

Identify the expected frontend route.

Example:

```text
POST /api/documents/generate-learning-objectives
```

Make sure the backend route is reachable exactly as expected, considering existing router prefixes.

### 2. Create request and response schemas

Create Pydantic schemas under the correct schema folder.

For a generation API:

* Request schema should validate required frontend fields.
* Response schema should return only the agreed contract.
* Use camelCase if frontend contract uses camelCase.

For Learning Objective generation, response must be:

```python
learningObjectives: list[str]
validationPassed: bool
repairAttempts: int
finalIssues: list[dict]
```

### 3. Create endpoint

Endpoint should:

* Accept request schema.
* Call service.
* Return response schema.
* Contain no business logic.
* Contain no direct orchestrator logic.
* Contain no direct agent calls.
* Contain no validation/repair loop.

### 4. Create service

Service should:

* Represent the application use case.
* Convert request DTO into internal orchestrator input.
* Call exactly one feature orchestrator method.
* Convert orchestrator result into API response DTO.
* Return result back to endpoint.

Service must not:

* Call agents directly.
* Run the repair loop.
* Build LLM prompts.

### 5. Update feature orchestrator

The feature orchestrator is the mediator between the outer application layer and agents.

The orchestrator should:

* Receive structured input from service.
* Call generation agent.
* Call validator agent.
* If validation fails, call refinement agent.
* Validate again.
* Repeat repair at most 2 times.
* Return final structured result to service.

Standard generation flow inside orchestrator:

```text
Generate
↓
Validate
↓
If validation passes, return immediately
↓
If validation fails, repair/refine using validation issues
↓
Validate again
↓
Repeat repair at most 2 times
↓
Return final result
```

### 6. Use agents correctly

Generation agent:

* Creates first output.

Validator agent:

* Checks output quality.
* Returns pass/fail and issue list.

Refinement agent:

* Receives previous output and validator issues.
* Produces improved output.

Agents should:

* Perform one specific LLM task.
* Accept structured input.
* Return structured output.

Agents must not:

* Import FastAPI route modules.
* Import endpoint request/response schemas.
* Know about endpoint, service, frontend, or HTTP.
* Coordinate other agents.
* Own repair-loop decisions.

### 7. Register router

Ensure the new endpoint is included in the existing API router.

Verify it appears in Swagger/OpenAPI.

### 8. Validate manually

Provide a curl command or test request.

Expected response shape:

```json
{
  "learningObjectives": ["..."],
  "validationPassed": true,
  "repairAttempts": 0,
  "finalIssues": []
}
```

## Learning Objective Generation Rules

For this endpoint:

```text
POST /api/documents/generate-learning-objectives
```

The approved flow is:

```text
Endpoint
↓
LearningObjectiveService.generate_learning_objectives()
↓
LearningObjectiveOrchestrator.generate_learning_objectives()
↓
LOGenerationAgent
↓
LOValidatorAgent
↓
LORefinementAgent if needed
↓
LearningObjectiveOrchestrator
↓
LearningObjectiveService
↓
Endpoint response
```

Repair rules:

* Maximum repair attempts: 2
* `repairAttempts = 0` if generated output passes first validation.
* `repairAttempts = 1` if one repair was performed.
* `repairAttempts = 2` if two repairs were performed.
* Stop immediately when validation passes.
* If validation never passes, return latest output with `validationPassed = false`.
* Return unresolved issues in `finalIssues`.

## Regeneration / User Prompt Refinement

Do not implement regenerate/refine API in this task.

If frontend sends future fields like:

```json
{
  "regenerationPrompt": "...",
  "currentObjectives": []
}
```

The generation API may accept them as optional fields for compatibility, but must not use them.

A future regenerate/refine API should be separate, for example:

```python
LearningObjectiveService.refine_with_prompt()
LearningObjectiveOrchestrator.refine_with_prompt()
```

## Quality Checklist

Before finishing, verify:

* Backend starts without import errors.
* Endpoint is visible in Swagger/OpenAPI.
* Endpoint calls service only.
* Service calls orchestrator only.
* Orchestrator calls agents.
* Agents do not know about FastAPI.
* Repair loop is inside orchestrator only.
* Repair loop stops immediately on validation pass.
* Repair loop never exceeds 2 attempts.
* Response shape exactly matches contract.
* Extra frontend fields for future regenerate API are ignored.
* No unrelated refactor was introduced.

## Final Response Format

When done, report:

1. Files created/updated
2. Final route
3. Flow confirmation
4. Response contract
5. Manual test command
6. Any assumptions or known limitations
