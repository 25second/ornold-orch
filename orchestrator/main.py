import shared.logging_config
from fastapi import FastAPI, HTTPException
import uuid
import json
from typing import List
import redis
import os
from .schemas import Task, TaskCreate, ResumeTaskRequest
from .orchestrator import orchestrator_instance
import logging

# Получаем хост Redis из переменной окружения
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
redis_client = redis.Redis(host=REDIS_HOST, port=6379, db=0, decode_responses=True)

logger = logging.getLogger(__name__)

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Orchestrator is running"}

@app.post("/tasks", response_model=Task, status_code=201)
async def create_task(task_request: TaskCreate):
    task = await orchestrator_instance.create_task(task_request)
    return await orchestrator_instance.start_task(task)


@app.get("/tasks", response_model=List[Task])
async def get_all_tasks():
    tasks = []
    # Используем scan_iter для безопасного сканирования ключей в Redis
    for key in orchestrator_instance.redis_client.scan_iter("task:*"):
        # Убедимся, что это ключ задачи, а не ключ для celery_id
        if "celery_id" not in key:
            task_data = orchestrator_instance.redis_client.hgetall(key)
            if task_data:
                # Восстанавливаем browser_endpoints из JSON-строки, если они есть
                if 'browser_endpoints' in task_data and task_data['browser_endpoints']:
                    try:
                        task_data['browser_endpoints'] = json.loads(task_data['browser_endpoints'])
                    except json.JSONDecodeError:
                        # В случае ошибки парсинга, оставляем как есть или ставим None
                        task_data['browser_endpoints'] = None
                else:
                    # Убедимся, что поле существует, даже если оно null, для соответствия модели
                    task_data['browser_endpoints'] = None
                
                tasks.append(Task(**task_data))
    return tasks


@app.get("/tasks/{task_id}", response_model=Task)
async def get_task_status(task_id: str):
    task_data = orchestrator_instance.get_task_status(task_id)
    if task_data is None:
        raise HTTPException(status_code=404, detail=f"Задача с ID {task_id} не найдена")
    return Task(**task_data)

@app.post("/tasks/{task_id}/stop", response_model=Task)
async def stop_task(task_id: str):
    """
    Принудительно останавливает выполнение задачи.
    """
    logger.info(f"Получен запрос на остановку задачи {task_id}")
    stopped_task_data = orchestrator_instance.stop_task(task_id)
    if stopped_task_data is None:
        raise HTTPException(status_code=404, detail=f"Задача с ID {task_id} не найдена для остановки")
    return Task(**stopped_task_data)

@app.post("/tasks/{task_id}/resume", response_model=Task)
async def resume_task(task_id: str, resume_request: ResumeTaskRequest):
    """
    Возобновляет выполнение задачи после вмешательства человека.
    """
    logger.info(f"Получен запрос на возобновление задачи {task_id} с действием: '{resume_request.action}'")
    resumed_task = await orchestrator_instance.resume_task_with_human_action(task_id, resume_request.action)
    if resumed_task is None:
        raise HTTPException(status_code=404, detail=f"Задача с ID {task_id} не найдена или не находится в статусе 'human_intervention'")
    return resumed_task 