from .schemas import Task
# Мы больше не импортируем SessionAgent напрямую
# from session_agent.agent import SessionAgent 
from worker import run_agent_task # Импортируем одну, универсальную задачу
import logging

logger = logging.getLogger(__name__)

class Orchestrator:
    async def start_task(self, task):
        logger.info(f"Запуск задачи '{task.goal}' (ID: {task.id})")

        # Просто ставим задачу в очередь. Агент сам решит, что делать.
        run_agent_task.delay(
            task_id=task.id,
            goal=task.goal,
            initial_browser_endpoints=task.browser_endpoints or []
        )

        task.status = "queued"
        return task

orchestrator_instance = Orchestrator() 