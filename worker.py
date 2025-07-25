import shared.logging_config
from celery import Celery
from universal_agent.agent import LaVagueAgent # Импортируем нового агента
import os

# Получаем хост Redis из переменной окружения
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")

# Настраиваем Celery
celery_app = Celery(
    'tasks',
    broker=f'redis://{REDIS_HOST}:6379/0',
    backend=f'redis://{REDIS_HOST}:6379/0'
)

@celery_app.task(name="worker.run_agent_task")
def run_agent_task(task_id: str, goal: str, initial_browser_endpoints: list = None):
    """
    Celery-задача, которая инициализирует и запускает LaVague агента.
    """
    agent = LaVagueAgent(
        task_id=task_id, 
        goal=goal,
        browser_endpoints=initial_browser_endpoints
    )
    agent.run()
    return f"Агент LaVague завершил работу над задачей {task_id}." 