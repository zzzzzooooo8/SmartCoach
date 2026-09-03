from typing import Literal

from pydantic import BaseModel, Field


class ProfileInput(BaseModel):
    user_id: str = "default"
    gender: Literal["male", "female"]
    age: int = Field(ge=16, le=100)
    height_cm: float = Field(ge=120, le=230)
    current_weight_kg: float = Field(ge=30, le=300)
    target_weight_kg: float | None = Field(default=None, ge=30, le=300)
    activity_level: Literal["sedentary", "light", "moderate", "heavy"]
    target_loss_speed: float = Field(default=0.5, ge=0.2, le=1.0)
    dietary_restrictions: list[str] = Field(default_factory=list)
    health_notes: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    user_id: str = "default"
    conversation_id: str = "main"


class UserActionRequest(BaseModel):
    user_id: str = "default"


class DietRecordInput(BaseModel):
    user_id: str = "default"
    food_name: str
    amount: float | None = None
    unit: str | None = None
    calories: float | None = Field(default=None, ge=0)
    protein_g: float | None = Field(default=None, ge=0)
    status: Literal["confirmed", "pending"] = "confirmed"


class ExerciseRecordInput(BaseModel):
    user_id: str = "default"
    exercise_name: str
    duration_minutes: float | None = Field(default=None, ge=0)
    intensity: str | None = None
    met: float | None = Field(default=None, ge=0)
    calories_burned: float | None = Field(default=None, ge=0)
    status: Literal["confirmed", "pending"] = "confirmed"


class MemoryStatusInput(BaseModel):
    user_id: str = "default"
    status: Literal["active", "ended", "pending_confirmation"]
