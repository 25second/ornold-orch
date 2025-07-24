import shared.logging_config
from celery import Celery
from session_agent.agent import SessionAgent
import asyncio
import os

# Получаем хост Redis из переменной окружения, по умолчанию 'localhost'
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")

# Настраиваем Celery. Используем Redis в качестве брокера и бэкенда для результатов.
celery_app = Celery(
    'tasks',
    broker=f'redis://{REDIS_HOST}:6379/0',
    backend=f'redis://{REDIS_HOST}:6379/0'
)

@celery_app.task
def run_web_agent_task(task_id: str, browser_endpoint_url: str, plan: list[str]):
    """
    Celery-задача, которая инициализирует и запускает сессионного агента.
    """
    agent = SessionAgent(task_id=task_id, browser_endpoint_url=browser_endpoint_url)
    asyncio.run(agent.run_task(plan))
    return f"Агент для эндпоинта {browser_endpoint_url} завершил работу над задачей {task_id}." 