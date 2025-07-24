from .schemas import Task
# Мы больше не импортируем SessionAgent напрямую
# from session_agent.agent import SessionAgent 
from worker import run_web_agent_task
from shared.memory import rag_memory_instance
from shared.llm_client import llm_client
import logging
import asyncio

logger = logging.getLogger(__name__)

class Orchestrator:
    def __init__(self):
        # self.session_agents больше не нужен, т.к. воркеры независимы
        pass

    async def start_task(self, task: Task):
        """
        Ставит задачи в очередь Celery для каждого профиля.
        """
        print(f"Запускаю задачу {task.id}: {task.goal}")
        
        plan = self._create_plan(task.goal)
        logger.info(f"Создан план: {plan}")

        for endpoint_url in task.browser_endpoints:
            logger.info(f"Ставлю в очередь задачу для эндпоинта: {endpoint_url}")
            run_web_agent_task.delay(
                task_id=task.id,
                browser_endpoint_url=endpoint_url,
                plan=plan
            )
        
        task.status = "queued"
        return task

    def _create_plan(self, goal: str) -> list[str]:
        """
        Создает план, используя RAG для поиска похожих успешных сценариев.
        """
        print(f"Ищу похожие сценарии для цели: '{goal}'")
        similar_scenarios = rag_memory_instance.search_similar_scenarios(goal, n_results=1)

        # Проверяем, нашлись ли сценарии и достаточно ли они похожи (пока порог 0.8)
        if similar_scenarios and similar_scenarios.get('distances') and similar_scenarios['distances'][0][0] < 0.2:
            print("Найден похожий сценарий! Использую его.")
            # Извлекаем шаги из документа
            document = similar_scenarios['documents'][0][0]
            steps = [line.replace("Шаг: ", "") for line in document.split('\n') if line.startswith("Шаг:")]
            return steps
        
        logger.info("Похожих сценариев не найдено. Создаю новый план через LLM.")
        
        # Вызов LLM для создания плана с нуля (теперь синхронный)
        response = llm_client.create_plan_for_goal(goal)
        new_plan = response.get("plan", [])

        if not new_plan:
            print("LLM не смог создать план. Использую дефолтную заглушку.")
            # Дефолтная заглушка на случай, если LLM не справился
            return [f"Шаг 1: Открыть главную страницу для '{goal}'"]

        # Сохраняем новый успешный сценарий в память для будущего использования
        rag_memory_instance.add_successful_scenario(goal, new_plan)

        return new_plan

# Синглтон экземпляр Оркестратора
orchestrator_instance = Orchestrator() 