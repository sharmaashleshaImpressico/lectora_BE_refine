"""Wire message shapes exchanged over the course-generation Service Bus queue."""

from __future__ import annotations

import json

from pydantic import BaseModel


class CourseGenerationJobMessage(BaseModel):
    """Minimal message published when a job is queued.

    Intentionally carries only the two ids needed to look everything else up
    from the database — the worker re-loads all generation inputs itself via
    `course_run_id`, so the message body never grows with the payload.
    """

    job_id: str
    course_run_id: str

    def to_body(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_body(cls, body: str | bytes) -> "CourseGenerationJobMessage":
        if isinstance(body, bytes):
            body = body.decode("utf-8")
        return cls.model_validate(json.loads(body))
