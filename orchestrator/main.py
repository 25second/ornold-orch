import shared.logging_config
from fastapi import FastAPI, HTTPException
import uuid
import json
from typing import List
import redis
import os
from .schemas import Task, TaskCreate, ResumeTaskRequest
from .orchestrator import orchestrator_instance
from worker import run_agent_task
import logging

# Получаем хост Redis из переменной окружения
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
redis_client = redis.Redis(host=REDIS_HOST, port=6379, db=0, decode_responses=True)

logger = logging.getLogger(__name__)

app = FastAPI(title="Web Agent Orchestrator")


@app.get("/")
def read_root():
    return {"message": "Orchestrator is running"}

@app.post("/tasks", response_model=Task)
async def create_task(task_create: TaskCreate):
    task_id = str(uuid.uuid4())
    task = Task(id=task_id, **task_create.model_dump())
    
    task = await orchestrator_instance.start_task(task)

    # Сохраняем задачу в Redis
    redis_client.set(f"task:{task_id}", task.model_dump_json())
    
    return task

@app.get("/tasks", response_model=List[Task])
def get_tasks():
    task_keys = redis_client.keys("task:*")
    tasks = []
    for key in task_keys:
        task_json = redis_client.get(key)
        if not task_json:
            continue
        try:
            # Пытаемся валидировать JSON. Если не получается - пропускаем.
            tasks.append(Task.model_validate_json(task_json))
        except Exception:
            # Логируем ошибку, чтобы знать о проблемных ключах.
            # В проде можно убрать, если будет слишком "шумно".
            logger.warning(f"Не удалось распарсить JSON для ключа '{key}'. Значение: '{task_json}'")
            continue
    return tasks

@app.get("/tasks/{task_id}", response_model=Task)
def get_task(task_id: str):
    task_json = redis_client.get(f"task:{task_id}")
    if not task_json:
        # Тут можно добавить обработку ошибки 404
        raise HTTPException(status_code=404, detail="Task not found")
    return Task.model_validate_json(task_json)


@app.post("/tasks/{task_id}/stop", response_model=Task)
async def stop_task(task_id: str):
    """
    Принудительно останавливает выполнение задачи.
    """
    logger.info(f"Получен запрос на остановку задачи {task_id}")
    stopped_task_data = orchestrator_instance.stop_task(task_id)
    if stopped_task_data is None:
        raise HTTPException(status_code=404, detail=f"Задача с ID {task_id} не найдена для остановки")
    return Task(**stopped_task_data, id=task_id)


@app.post("/tasks/{task_id}/resume", response_model=Task)
def resume_task(task_id: str, resume_request: ResumeTaskRequest):
    """
    Возобновляет задачу, застрявшую на этапе Human Intervention.
    """
    task_json = redis_client.get(f"task:{task_id}")
    if not task_json:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = Task.model_validate_json(task_json)
    if task.status != 'human_intervention_required':
        raise HTTPException(status_code=400, detail=f"Task status is '{task.status}', not 'human_intervention_required'")

    logger.info(f"Возобновляю задачу {task_id} с новым действием от оператора: {resume_request.action}")

    # Извлекаем URL "зависшего" браузера из контекста ошибки
    failed_context = task.failed_action_context or {}
    browser_endpoint_url = failed_context.get("browser_endpoint_url")
    
    if not browser_endpoint_url:
        raise HTTPException(status_code=400, detail="Не удалось найти browser_endpoint_url в контексте ошибки для возобновления.")

    # Создаем новый, простой план из одного действия, предоставленного оператором.
    # В новой архитектуре агент не использует "план", а действует по шагам.
    # Мы можем передать ему новую цель.
    new_goal = f"Возобновляю работу. Следующее действие, продиктованное человеком: {resume_request.action}"

    logger.info(f"Отправляю задачу на возобновление для эндпоинта: {browser_endpoint_url}")
    run_agent_task.delay(
        task_id=task.id,
        goal=new_goal, 
        initial_browser_endpoints=[browser_endpoint_url]
    )

    task.status = "queued"
    redis_client.set(f"task:{task.id}", task.model_dump_json())
    
    return task 