import shared.logging_config
from celery import Celery
from session_agent.agent import SessionAgent
import asyncio

# Настраиваем Celery. Используем Redis в качестве брокера и бэкенда для результатов.
celery_app = Celery(
    'tasks',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/0'
)

@celery_app.task
def run_web_agent_task(task_id: str, profile_id: str, cdp_port: int, plan: list[str]):
    """
    Celery-задача, которая инициализирует и запускает сессионного агента.
    """
    agent = SessionAgent(task_id=task_id, profile_id=profile_id, cdp_port=cdp_port)
    asyncio.run(agent.run_task(plan))
    return f"Агент {profile_id} завершил работу над задачей {task_id}." 