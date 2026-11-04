"""Data contracts: task specs, actions, limits (architecture.md section 7).

Pydantic models here are the source of truth for what the harness accepts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, TypeAdapter, ValidationError, model_validator

# --- Actions (architecture.md 7.2) -------------------------------------------


class _MarkOrCoords(BaseModel):
    """Pointer action with either coordinates or an L2 set-of-marks ID."""

    x: int | None = None
    y: int | None = None
    mark: int | None = None  # 1-based: act on the center of OCR mark #mark

    @model_validator(mode="after")
    def _needs_target(self):
        if self.x is None and self.mark is None:
            raise ValueError("pointer action requires x/y or a mark")
        return self


class Click(_MarkOrCoords):
    type: Literal["click"] = "click"
    button: Literal["left", "right", "middle"] = "left"


class DoubleClick(_MarkOrCoords):
    type: Literal["double_click"] = "double_click"


class Drag(BaseModel):
    type: Literal["drag"] = "drag"
    x1: int
    y1: int
    x2: int
    y2: int


class Move(_MarkOrCoords):
    type: Literal["move"] = "move"


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


class Milestone(BaseModel):
    """Partial-credit checkpoint, scored by the judge like the main evidence."""

    name: str
    check: str


class SuccessConfig(BaseModel):
    evidence: str
    evidence_step: str | None = None
    verifiers: list[str] = ["vlm"]
    milestones: list[Milestone] = Field(default_factory=list)


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
    max_stuck_events: int = 6  # 0 disables the stuck budget


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
