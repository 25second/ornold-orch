import asyncio
import json
import logging
import redis
from playwright.async_api import async_playwright, Browser, Page
from typing import Optional, List

from shared.llm_client import llm_client
from shared.dom_processor import mark_interactive_elements
from shared.memory import rag_memory_instance
import os

# --- Клиенты и логгер ---
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
redis_client = redis.Redis(host=REDIS_HOST, port=6379, db=0, decode_responses=True)
logger = logging.getLogger(__name__)

class UniversalAgent:
    def __init__(self, task_id: str, goal: str, initial_browser_endpoints: List[str]):
        self.task_id = task_id
        self.goal = goal
        self.available_browser_endpoints = initial_browser_endpoints
        
        # Внутреннее состояние агента
        self.internal_thoughts: List[str] = []
        self.history: List[dict] = []
        self.is_finished = False
        
        # Состояние браузера (инициализируется как None)
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None

    async def run(self):
        logger.info(f"Агент {self.task_id} начинает работу над целью: '{self.goal}'")
        self.update_task_status("in_progress")

        while not self.is_finished:
            # 1. Агент "думает", какое действие совершить следующим
            next_action = await self._decide_next_action()
            self.history.append(next_action)
            
            # 2. Агент выполняет действие
            await self._execute_action(next_action)

        logger.info(f"Агент {self.task_id} завершил работу.")

    async def _decide_next_action(self) -> dict:
        """Основной мыслительный цикл агента."""
        # Здесь мы могли бы сначала искать в памяти похожие задачи,
        # но для простоты пока будем всегда обращаться к LLM.
        
        # Получаем текущее "восприятие" мира
        perception = await self._get_perception_data()

        return await llm_client.get_next_action_universal(
            goal=self.goal,
            history=self.history,
            perception=perception
        )

    async def _get_perception_data(self) -> dict:
        """Собирает текущее состояние мира для агента."""
        perception = {
            "browser_open": self.page is not None,
            "current_url": self.page.url if self.page else None,
            "marked_html": None
        }
        if self.page:
            raw_html = await self.page.content()
            perception["marked_html"] = mark_interactive_elements(raw_html)
        
        return perception

    async def _execute_action(self, action: dict):
        action_type = action.get("action")
        logger.info(f"Агент {self.task_id} выполняет действие: {action_type}")

        try:
            if action_type == "think":
                self.internal_thoughts.append(action.get("text", ""))
            
            elif action_type == "browse":
                await self._action_browse(action.get("url"))

            elif action_type == "click":
                await self._action_click(action.get("element_id"))
            
            elif action_type == "type":
                await self._action_type(action.get("element_id"), action.get("text"))

            elif action_type == "finish":
                self._action_finish(action.get("result"))
            
            else:
                raise ValueError(f"Неизвестный тип действия: {action_type}")

        except Exception as e:
            logger.error(f"Ошибка при выполнении действия {action}: {e}")
            # Здесь можно будет встроить старый механизм восстановления
            self.update_task_status("error", status_reason=str(e))
            self.is_finished = True

    # --- Реализации действий ---

    async def _action_browse(self, url: str):
        if not self.browser:
            if not self.available_browser_endpoints:
                raise ConnectionError("Агент решил использовать браузер, но ему не предоставили эндпоинт.")
            
            # Берем первый доступный эндпоинт
            endpoint = self.available_browser_endpoints.pop(0)
            logger.info(f"Агент {self.task_id} запрашивает браузер, подключаюсь к {endpoint}...")
            p = await async_playwright().start()
            self.browser = await p.chromium.connect_over_cdp(endpoint)
            self.page = self.browser.contexts[0].pages[0]

        logger.info(f"Агент {self.task_id} переходит по URL: {url}")
        await self.page.goto(url)

    async def _action_click(self, element_id: str):
        if not self.page: raise ConnectionError("Нельзя кликнуть, браузер не открыт.")
        selector = f"[data-ornold-id='{element_id}']"
        # Здесь можно вернуть human_like_click
        await self.page.locator(selector).click()

    async def _action_type(self, element_id: str, text: str):
        if not self.page: raise ConnectionError("Нельзя печатать, браузер не открыт.")
        selector = f"[data-ornold-id='{element_id}']"
        # Здесь можно вернуть human_like_type
        await self.page.locator(selector).type(text)

    def _action_finish(self, result: str):
        logger.info(f"Агент {self.task_id} завершает работу с результатом: {result}")
        self.update_task_status("completed", result=result)
        self.is_finished = True

    # --- Вспомогательные методы ---
    
    def update_task_status(self, status: str, status_reason: str = None, result: str = None):
        task_json = redis_client.get(f"task:{self.task_id}")
        if not task_json: return
        
        task_data = json.loads(task_json)
        task_data['status'] = status
        if status_reason: task_data['status_reason'] = status_reason
        if result: task_data['result'] = result
        
        redis_client.set(f"task:{self.task_id}", json.dumps(task_data)) 