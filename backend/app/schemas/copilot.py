"""Creator Copilot response schemas (V1.6). Creator-facing only: no ids beyond what routes
already carry, no handles, prompts, model names or context internals."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class CopilotContextRead(BaseModel):
    """What the Copilot can see from here, in a few words (the panel's context label)."""

    page: str
    scope: str  # "Your workspace" or the project's name
    facts: list[str]


class CopilotActionRead(BaseModel):
    """An action offered under an answer. ``index`` identifies it within its message for
    ``POST /copilot/messages/{id}/actions/{index}`` (re-validated before any use)."""

    index: int
    type: str
    label: str


class CopilotReferenceRead(BaseModel):
    kind: str
    label: str  # e.g. "Moment: The night before the test", never an id


class CopilotMessageRead(BaseModel):
    id: uuid.UUID
    role: str  # "user" or "assistant"
    content: str
    suggestion: str | None
    status: str  # "ok", or "unavailable" when the local assistant could not answer
    page: str
    actions: list[CopilotActionRead]
    references: list[CopilotReferenceRead]
    created_at: datetime


class CopilotThreadRead(BaseModel):
    scope: str  # "Your workspace" or the project's name
    messages: list[CopilotMessageRead]
