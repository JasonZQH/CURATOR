"""Define shared Pydantic model configuration."""

from pydantic import BaseModel, ConfigDict


class CuratorModel(BaseModel):
    """Provide shared Pydantic settings for Curator contracts."""

    model_config = ConfigDict(extra="forbid")


AgentctlModel = CuratorModel
