from magnitude import BrowserAgent
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

class MagnitudeAgent:
    def __init__(self, task_id: str, goal: str, browser_endpoints: Optional[List[str]] = None):
        self.task_id = task_id
        self.goal = goal
        self.browser_endpoints = browser_endpoints

    def run(self):
        logger.info(f"Агент Magnitude {self.task_id} начинает работу над целью: '{self.goal}'")
        self.update_task_status("in_progress")

        # --- Конфигурация Magnitude ---
        os.environ["OPENAI_API_KEY"] = os.getenv("RUNPOD_API_KEY")
        os.environ["OPENAI_API_BASE"] = f"https://api.runpod.ai/v2/{os.getenv('RUNPOD_ENDPOINT_ID_GEMMA')}/openai/v1"

        try:
            browser_options = {}
            if self.browser_endpoints:
                endpoint = self.browser_endpoints[0]
                logger.info(f"Подключаюсь к удаленному браузеру по эндпоинту: {endpoint}")
                
                # Magnitude ожидает HTTP-адрес для CDP, а не WebSocket URL.
                # Мы просто берем хост и порт из вашего эндпоинта.
                parsed_url = urllib.parse.urlparse(endpoint)
                
                # Получаем порт из WebSocket URL, который отдает браузер
                response = requests.get(endpoint)
                ws_url = response.json().get("webSocketDebuggerUrl")
                ws_port = urllib.parse.urlparse(ws_url).port

                cdp_address = f"http://{parsed_url.hostname}:{ws_port}"
                logger.info(f"Использую CDP адрес: {cdp_address}")
                browser_options["cdp"] = cdp_address
            else:
                logger.info("Эндпоинты не предоставлены, Magnitude запустит свой браузер.")

            agent = BrowserAgent(browser=browser_options)
            agent.goto(self.goal)
            
            final_result = f"Magnitude успешно выполнил цель: {self.goal}"
            logger.info(final_result)
            self.update_task_status("completed", result=final_result)

        except Exception as e:
            error_message = f"Ошибка во время выполнения Magnitude: {e}"
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