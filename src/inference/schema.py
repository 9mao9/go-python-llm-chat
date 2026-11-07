from pydantic import BaseModel, ConfigDict, Field


class OutputSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="Assistant response text")
