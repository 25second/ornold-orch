from lavague import LaVague, Action, WorldModel
from lavague_drivers.playwright import PlaywrightDriver
from lavague_llms.ollama import Ollama
import logging
import json
import redis
import os
import requests
import urllib.parse
from typing import List, Optional

# --- Конфигурация ---
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
redis_client = redis.Redis(host=REDIS_HOST, port=6379, db=0, decode_responses=True)
logger = logging.getLogger(__name__)

# --- Настройка LLM для LaVague (Ollama) ---
ollama_llm = Ollama(
    llm_config={
        "model": "gemma3:12b",  # Название вашей модели
        "base_url": f"https://api.runpod.ai/v2/{os.getenv('RUNPOD_ENDPOINT_ID_GEMMA')}/openai/v1",
        "api_key": os.getenv("RUNPOD_API_KEY"),
    }
)
world_model = WorldModel(ollama_llm)
action_engine = Action(ollama_llm)

class LaVagueAgent:
    def __init__(self, task_id: str, goal: str, browser_endpoints: Optional[List[str]] = None):
        self.task_id = task_id
        self.goal = goal
        self.browser_endpoints = browser_endpoints
        self.driver = None

    def _connect_to_browser(self):
        """Подключается к удаленному браузеру, если предоставлен эндпоинт."""
        if not self.browser_endpoints:
            logger.info("Эндпоинты не предоставлены, LaVague запустит свой браузер.")
            self.driver = PlaywrightDriver() # LaVague создаст свой браузер
            return

        endpoint = self.browser_endpoints[0]
        logger.info(f"Подключаюсь к удаленному браузеру по эндпоинту: {endpoint}")

        try:
            response = requests.get(endpoint, timeout=20)
            response.raise_for_status()
            browser_info = response.json()
            ws_url = browser_info.get("webSocketDebuggerUrl")
            
            if not ws_url:
                raise ConnectionError(f"Не удалось получить webSocketDebuggerUrl из {endpoint}")
            
            parsed_endpoint = urllib.parse.urlparse(endpoint)
            ws_url = ws_url.replace("127.0.0.1", parsed_endpoint.hostname).replace("localhost", parsed_endpoint.hostname)
            
            # Убираем порт, если он есть
            parsed_ws_url = urllib.parse.urlparse(ws_url)
            if parsed_ws_url.port:
                ws_url = parsed_ws_url._replace(netloc=parsed_ws_url.hostname).geturl()

            logger.info(f"Итоговый WebSocket URL для подключения: {ws_url}")
            self.driver = PlaywrightDriver(cdp=ws_url)

        except Exception as e:
            logger.error(f"Не удалось подключиться к удаленному браузеру: {e}")
            raise # Перебрасываем исключение, чтобы задача упала с ошибкой

    def run(self):
        logger.info(f"Агент LaVague {self.task_id} начинает работу над целью: '{self.goal}'")
        self.update_task_status("in_progress")

        try:
            self._connect_to_browser()
            lavague_instance = LaVague(self.driver, action_engine, world_model)
            lavague_instance.run(self.goal)
            
            final_result = f"LaVague успешно выполнил цель: {self.goal}"
            logger.info(final_result)
            self.update_task_status("completed", result=final_result)

        except Exception as e:
            error_message = f"Ошибка во время выполнения LaVague: {e}"
            logger.error(error_message)
            self.update_task_status("error", status_reason=str(e))
    
    def update_task_status(self, status: str, status_reason: str = None, result: str = None):
        """Обновляет статус задачи в Redis."""
        task_json = redis_client.get(f"task:{self.task_id}")
        if not task_json:
            logger.warning(f"Не удалось найти задачу {self.task_id} в Redis для обновления статуса.")
            return
        
        task_data = json.loads(task_json)
        task_data['status'] = status
        if status_reason: task_data['status_reason'] = status_reason
        if result: task_data['result'] = result
        
        redis_client.set(f"task:{self.task_id}", json.dumps(task_data)) 