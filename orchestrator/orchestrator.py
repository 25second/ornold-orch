from .schemas import Task
# Мы больше не импортируем SessionAgent напрямую
# from session_agent.agent import SessionAgent 
from worker import run_agent_task, celery_app
import logging
import redis
import os

logger = logging.getLogger(__name__)

class Orchestrator:
    def __init__(self):
        self.redis_client = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), port=6379, db=0)
        self.celery_app = celery_app

    async def start_task(self, task: Task):
        logger.info(f"Запуск задачи '{task.goal}' (ID: {task.id})")
        
        async_result = run_agent_task.delay(
            task_id=task.id,
            goal=task.goal,
            initial_browser_endpoints=task.browser_endpoints or []
        )
        
        celery_task_id = async_result.id
        self.redis_client.set(f"task:celery_id:{task.id}", celery_task_id)
        logger.info(f"Задача {task.id} запущена в Celery с ID {celery_task_id}")

        task.status = "queued"
        return task

    def get_task_status(self, task_id: str) -> dict | None:
        task_data_bytes = self.redis_client.hgetall(f"task:{task_id}")
        if not task_data_bytes:
            return None
        return {key.decode(): value.decode() for key, value in task_data_bytes.items()}

    def stop_task(self, task_id: str) -> dict | None:
        """Принудительно останавливает задачу."""
        task_data = self.get_task_status(task_id)
        if not task_data:
            logger.warning(f"Попытка остановить несуществующую задачу: {task_id}")
            return None

        celery_task_id_bytes = self.redis_client.get(f"task:celery_id:{task_id}")

        if celery_task_id_bytes:
            celery_task_id = celery_task_id_bytes.decode()
            logger.info(f"Отправка команды на остановку для Celery задачи {celery_task_id} (наша задача {task_id})")
            self.celery_app.control.revoke(celery_task_id, terminate=True, signal='SIGKILL')
        else:
            logger.warning(f"Не найден Celery ID для задачи {task_id}. Возможно, она уже завершена. Статус будет обновлен на 'stopped'.")

        self.redis_client.hset(f"task:{task_id}", "status", "stopped")
        self.redis_client.hset(f"task:{task_id}", "status_reason", "Принудительно остановлена пользователем.")
        
        logger.info(f"Статус задачи {task_id} обновлен на 'stopped'.")
        return self.get_task_status(task_id)

orchestrator_instance = Orchestrator() 