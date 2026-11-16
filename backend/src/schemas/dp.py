from pydantic import BaseModel, Field, field_validator

from src.services.dp_mechanism import DP_MAX_MICROS, DP_MICROS, epsilon_to_micros


def _finite_positive(value):
    if isinstance(value, bool):
        raise ValueError('ε必须为有限正数')
    epsilon_to_micros(value)
    return value


class DpBudgetInput(BaseModel):
    study_id: int
    total_epsilon: float = Field(gt=0, le=DP_MAX_MICROS / DP_MICROS, allow_inf_nan=False)

    @field_validator('total_epsilon', mode='before')
    @classmethod
    def check_total(cls, value):
        return _finite_positive(value)


class DpBudgetOut(BaseModel):
    study_id: int
    total_epsilon: float
    spent_epsilon: float
    remaining_epsilon: float
    preset_by: str
    created_at: str


class DpReleaseInput(BaseModel):
    study_id: int
    name: str = Field(min_length=2, max_length=140)
    epsilon: float = Field(gt=0, le=DP_MAX_MICROS / DP_MICROS, allow_inf_nan=False)

    @field_validator('epsilon', mode='before')
    @classmethod
    def check_epsilon(cls, value):
        return _finite_positive(value)


class DpReleaseOut(BaseModel):
    id: int
    study_id: int
    epsilon: float
    status: str
    release_digest: str
    names: list[str]
    result: dict | None
    error: str
    reused: bool
    created_at: str
