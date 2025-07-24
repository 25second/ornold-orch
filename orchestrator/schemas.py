from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class TaskCreate(BaseModel):
    goal: str
    browser_endpoints: Optional[List[str]] = Field(
        None,
        description="(Опционально) Список URL-адресов эндпоинтов браузеров для предоставления агенту",
        examples=[["wss://your-tunnel-1.ngrok.io"]]
    )

class Task(TaskCreate):
    id: str
    status: str = "pending"
    status_reason: Optional[str] = None
    failed_action_context: Optional[Dict[str, Any]] = Field(
        None,
        description="Контекст для Human-in-the-Loop"
    )
    result: Optional[Any] = Field(None, description="Финальный результат выполнения задачи")

class ResumeTaskRequest(BaseModel):
    action: Dict[str, Any] = Field(
        ...,
        example={"action": "click", "element_id": "#new_selector_provided_by_human"}
    ) 