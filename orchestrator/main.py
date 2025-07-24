import shared.logging_config
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
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

app = FastAPI(title="Web Agent Orchestrator")

# Настройка шаблонов
templates = Jinja2Templates(directory="orchestrator/templates")

# Простая аутентификация
def is_authenticated(request: Request):
    auth_cookie = request.cookies.get("auth")
    if auth_cookie != "supersecretcookie": # В реальном приложении это должно быть безопасно
        raise HTTPException(status_code=401, detail="Не авторизован")
    return True

@app.get("/login")
def login_form(request: Request):
    # Простая форма входа для демонстрации
    return HTMLResponse("""
        <h1>Вход в админ-панель</h1>
        <form action="/login" method="post">
            <input type="password" name="password" placeholder="Пароль">
            <button type="submit">Войти</button>
        </form>
    """)

@app.post("/login")
async def login(request: Request):
    form = await request.form()
    # В реальном приложении сверяем с FLOWER_USER/PASSWORD из .env
    if form.get("password") == "supersecretpassword": 
        response = RedirectResponse(url="/admin", status_code=302)
        response.set_cookie(key="auth", value="supersecretcookie", httponly=True)
        return response
    return "Неверный пароль", 400


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, authenticated: bool = Depends(is_authenticated)):
    tasks = orchestrator_instance.get_all_tasks()
    return templates.TemplateResponse("admin.html", {"request": request, "tasks": tasks})


@app.post("/admin/tasks/{task_id}/stop")
async def admin_stop_task(task_id: str, authenticated: bool = Depends(is_authenticated)):
    logger.info(f"Получен запрос на остановку задачи {task_id} из админ-панели")
    orchestrator_instance.stop_task(task_id)
    return RedirectResponse(url="/admin", status_code=303)


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

@app.get("/tasks", response_model=list[Task])
async def get_all_tasks():
    """
    Возвращает список всех задач.
    """
    tasks_data = orchestrator_instance.get_all_tasks()
    return [Task(**task) for task in tasks_data]


@app.get("/tasks/{task_id}", response_model=Task)
async def get_task_status(task_id: str):
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