"""Creator Copilot response schemas (V1.6). Creator-facing only: no ids beyond what routes
already carry, no handles, prompts, model names or context internals."""

from pydantic import BaseModel


class CopilotContextRead(BaseModel):
    """What the Copilot can see from here, in a few words (the panel's context label)."""

    page: str
    scope: str  # "Your workspace" or the project's name
    facts: list[str]
