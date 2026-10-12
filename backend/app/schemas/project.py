import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

ProjectName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ProjectCreate(BaseModel):
    name: ProjectName


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: str
    created_at: datetime
    updated_at: datetime
