"""Data contracts: task specs, actions, limits (architecture.md section 7).

Pydantic models here are the source of truth for what the harness accepts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

# --- Actions (architecture.md 7.2) -------------------------------------------


class Click(BaseModel):
    type: Literal["click"] = "click"
    x: int
    y: int
    button: Literal["left", "right", "middle"] = "left"


class DoubleClick(BaseModel):
    type: Literal["double_click"] = "double_click"
    x: int
    y: int


class Drag(BaseModel):
    type: Literal["drag"] = "drag"
    x1: int
    y1: int
    x2: int
    y2: int


class Move(BaseModel):
    type: Literal["move"] = "move"
    x: int
    y: int


class Key(BaseModel):
    type: Literal["key"] = "key"
    key: str
    hold_ms: int = 0


class Type_(BaseModel):
    type: Literal["type"] = "type"
    text: str


class Scroll(BaseModel):
    type: Literal["scroll"] = "scroll"
    x: int
    y: int
    dy: int = -3


class Wait(BaseModel):
    type: Literal["wait"] = "wait"
    ms: int = 500


class Note(BaseModel):
    type: Literal["note"] = "note"
    text: str


class Done(BaseModel):
    type: Literal["done"] = "done"
    claim: str = ""


Action = (
    Click | DoubleClick | Drag | Move | Key | Type_ | Scroll | Wait | Note | Done
)
ACTION_ADAPTER: TypeAdapter[list[Action]] = TypeAdapter(list[Action])


def parse_actions(raw: list[dict[str, Any]]) -> list[Action]:
    """Validate a raw list of action dicts; raises ValidationError on the first bad one."""
    return ACTION_ADAPTER.validate_python(raw)


# --- Task spec (architecture.md 7.1) -----------------------------------------


class SuccessConfig(BaseModel):
    evidence: str
    evidence_step: str | None = None
    verifiers: list[str] = ["vlm"]


class Limits(BaseModel):
    max_steps: int = 300
    max_wall_minutes: float = 45
    max_wall_hours: float | None = None  # attempt mode: primary cap
    max_cost_usd: float = 5.0


class ResearchConfig(BaseModel):
    mode: Literal["web", "none", "provided"] = "web"
    max_minutes: int = 10


class LoopConfig(BaseModel):
    time_mode: Literal["realtime", "paused"] = "realtime"
    assist_level: Literal["L0", "L1", "L2"] = "L0"
    topology: Literal["single", "hybrid"] = "single"
    decision_hz: float | None = None  # optional decision-rate throttle


class TaskSpec(BaseModel):
    id: str
    game: str
    title: str = ""
    goal: str
    tier: int = Field(default=1, ge=1, le=4)
    mode: Literal["study", "attempt"] = "study"
    start_state: str = ""
    baseline: dict[str, Any] = Field(default_factory=dict)  # modeled properly in Sprint 4
    success: SuccessConfig
    limits: Limits = Field(default_factory=Limits)
    checkpoint_every_steps: int = 25
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    loop: LoopConfig = Field(default_factory=LoopConfig)


def load_task_spec(path: str | Path) -> TaskSpec:
    """Load and validate a task spec YAML file."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValidationError.from_exception_data(
            "TaskSpec", [{"type": "model_type", "loc": (), "input": data}]
        )
    return TaskSpec.model_validate(data)
