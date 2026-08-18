from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from vypq_contracts.common import ModelKind, Task


class ModelSpec(BaseModel):
    id: str
    task: Task
    kind: ModelKind
    runner: str
    vram_mb: int = 0
    pinned: bool = False
    source: dict[str, str] = Field(default_factory=dict)
    base: str | None = None
    trained_on: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class HostConfig(BaseModel):
    host_name: str
    vram_budget_mb: int
    models: list[ModelSpec] = Field(default_factory=list)


def load_host_config(path: Path) -> HostConfig:
    return HostConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
