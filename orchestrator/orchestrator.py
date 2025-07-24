from .schemas import Task, TaskCreate
# Мы больше не импортируем SessionAgent напрямую
# from session_agent.agent import SessionAgent 
from worker import run_agent_task, celery_app
import logging
import redis
import os
import uuid
import json

logger = logging.getLogger(__name__)

class Orchestrator:
    def __init__(self):
        self.redis_client = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), port=6379, db=0, decode_responses=True)
        self.celery_app = celery_app

    async def create_task(self, task_request: TaskCreate) -> Task:
        """Создает объект задачи перед ее запуском."""
        task_id = str(uuid.uuid4())
        task = Task(id=task_id, **task_request.model_dump())
        
        # Сохраняем основную информацию о задаче в Redis
        task_info = {
            "id": task.id,
            "goal": task.goal,
            "status": "created", # Начальный статус
            "status_reason": "",
            "result": ""
        }
        # Добавляем browser_endpoints, если они есть
        if task.browser_endpoints:
            # Преобразуем список в строку, чтобы сохранить в hash
            task_info["browser_endpoints"] = json.dumps(task.browser_endpoints)
            
        self.redis_client.hset(f"task:{task.id}", mapping=task_info)
        logger.info(f"Задача {task.id} создана и сохранена в Redis.")
        return task

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

        self.redis_client.hset(f"task:{task.id}", "status", "queued")
        task.status = "queued"
        return task

    def get_task_status(self, task_id: str) -> dict | None:
        task_data = self.redis_client.hgetall(f"task:{task_id}")
        if not task_data:
            return None
        return task_data

    def stop_task(self, task_id: str) -> dict | None:
        """Принудительно останавливает задачу."""
        task_data = self.get_task_status(task_id)
        if not task_data:
            logger.warning(f"Попытка остановить несуществующую задачу: {task_id}")
            return None

        celery_task_id = self.redis_client.get(f"task:celery_id:{task_id}")

        if celery_task_id:
            logger.info(f"Отправка команды на остановку для Celery задачи {celery_task_id} (наша задача {task_id})")
            self.celery_app.control.revoke(celery_task_id, terminate=True, signal='SIGKILL')
        else:
            logger.warning(f"Не найден Celery ID для задачи {task_id}. Возможно, она уже завершена. Статус будет обновлен на 'stopped'.")

        self.redis_client.hset(f"task:{task_id}", "status", "stopped")
        self.redis_client.hset(f"task:{task_id}", "status_reason", "Принудительно остановлена пользователем.")
        
        logger.info(f"Статус задачи {task_id} обновлен на 'stopped'.")
        return self.get_task_status(task_id)
    
    async def resume_task_with_human_action(self, task_id: str, action: str) -> Task | None:
        """Возобновляет задачу с действием от человека."""
        task_data = self.get_task_status(task_id)
        if not task_data or task_data.get('status') != 'human_intervention_required':
            return None

        logger.info(f"Возобновляю задачу {task_id} с новым действием от оператора: {action}")
        
        failed_context_str = task_data.get("failed_action_context", "{}")
        failed_context = json.loads(failed_context_str)
        browser_endpoint_url = failed_context.get("browser_endpoint_url")

        if not browser_endpoint_url:
            logger.error(f"Не найден browser_endpoint_url в контексте ошибки для возобновления задачи {task_id}")
            # Обновляем статус, чтобы показать, что возобновление не удалось
            self.redis_client.hset(f"task:{task_id}", "status_reason", "Ошибка возобновления: не найден URL браузера.")
            return Task(**self.get_task_status(task_id))

        new_goal = f"Возобновляю работу. Следующее действие, продиктованное человеком: {action}"

        logger.info(f"Отправляю задачу на возобновление для эндпоинта: {browser_endpoint_url}")
        run_agent_task.delay(
            task_id=task_id,
            goal=new_goal,
            initial_browser_endpoints=[browser_endpoint_url]
        )

        self.redis_client.hset(f"task:{task_id}", "status", "queued")
        self.redis_client.hset(f"task:{task_id}", "status_reason", "Возобновлена оператором.")
        
        return Task(**self.get_task_status(task_id))

orchestrator_instance = Orchestrator() 