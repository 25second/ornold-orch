import shared.logging_config
from fastapi import FastAPI, HTTPException
import uuid
import json
from typing import List
import redis
from .schemas import Task, TaskCreate, ResumeTaskRequest
from .orchestrator import orchestrator_instance
from worker import run_web_agent_task

app = FastAPI(title="Web Agent Orchestrator")

# Подключаемся к Redis
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)


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
    tasks = [Task.model_validate_json(redis_client.get(key)) for key in task_keys]
    return tasks

@app.get("/tasks/{task_id}", response_model=Task)
def get_task(task_id: str):
    task_json = redis_client.get(f"task:{task_id}")
    if not task_json:
        # Тут можно добавить обработку ошибки 404
        raise HTTPException(status_code=404, detail="Task not found")
    return Task.model_validate_json(task_json)

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

    print(f"Возобновляю задачу {task_id} с новым действием от оператора: {resume_request.action}")

    # Здесь должна быть логика получения старого плана и добавления нового шага.
    # Для простоты, мы просто поставим в очередь одно это действие.
    # В реальной системе нужно было бы найти, на каком шаге произошла ошибка,
    # и перестроить остаток плана.
    new_plan = [f"Действие от оператора: {resume_request.action.get('action')} на {resume_request.action.get('element_id')}"]

    # TODO: Нам нужен profile_id и cdp_port, сохраненные в задаче.
    # Пока что хардкодим.
    profile_id = "profile_stuck" 
    cdp_port = 9222

    run_web_agent_task.delay(
        task_id=task.id,
        profile_id=profile_id, 
        cdp_port=cdp_port, 
        plan=new_plan # Отправляем новый мини-план
    )

    task.status = "queued"
    redis_client.set(f"task:{task.id}", task.model_dump_json())
    
    return task 