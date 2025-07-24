import shared.logging_config
from celery import Celery
from universal_agent.agent import UniversalAgent # Импортируем нового агента
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

@celery_app.task(name="worker.run_agent_task")
def run_agent_task(task_id: str, goal: str, initial_browser_endpoints: list):
    """
    Универсальная Celery-задача, которая инициализирует и запускает агента.
    """
    agent = UniversalAgent(
        task_id=task_id, 
        goal=goal,
        initial_browser_endpoints=initial_browser_endpoints
    )
    asyncio.run(agent.run())
    return f"Универсальный агент завершил работу над задачей {task_id}." 