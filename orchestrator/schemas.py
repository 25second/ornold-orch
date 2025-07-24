from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class TaskCreate(BaseModel):
    goal: str
    browser_endpoints: List[str] = Field(
        ...,
        description="Список URL-адресов эндпоинтов браузеров (например, от туннелей ngrok)",
        examples=[["wss://your-tunnel-1.ngrok.io", "wss://your-tunnel-2.ngrok.io"]]
    )

class Task(TaskCreate):
    id: str
    status: str = "pending"
    status_reason: Optional[str] = None
    failed_action_context: Optional[Dict[str, Any]] = Field(
        None,
        description="Контекст для Human-in-the-Loop, включая URL 'зависшего' браузера"
    )

class ResumeTaskRequest(BaseModel):
    action: Dict[str, Any] = Field(
        ...,
        example={"action": "click", "element_id": "#new_selector_provided_by_human"}
    ) 