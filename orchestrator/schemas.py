from pydantic import BaseModel, Field
from typing import List, Dict, Any

class TaskCreate(BaseModel):
    goal: str
    browser_profiles: List[str]

class Task(TaskCreate):
    id: str
    status: str = "pending"
    status_reason: str | None = None
    failed_action_context: Dict[str, Any] | None = None

class ResumeTaskRequest(BaseModel):
    action: Dict[str, Any] = Field(
        ...,
        example={"action": "click", "element_id": "#new_selector_provided_by_human"}
    ) 