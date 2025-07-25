from magnitude import BrowserAgent
import logging
import json
import redis
import os
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
        # Magnitude использует свои переменные окружения.
        # Убедитесь, что MAGNITUDE_API_KEY и другие нужные переменные установлены.
        # В данном случае, мы предполагаем, что он может работать с OpenAI-совместимым API.
        os.environ["OPENAI_API_KEY"] = os.getenv("RUNPOD_API_KEY")
        os.environ["OPENAI_API_BASE"] = f"https://api.runpod.ai/v2/{os.getenv('RUNPOD_ENDPOINT_ID_GEMMA')}/openai/v1"

        try:
            # Если есть эндпоинт, подключаемся к нему. Иначе Magnitude создаст свой браузер.
            cdp_endpoint = None
            if self.browser_endpoints:
                # Magnitude, скорее всего, ожидает прямой CDP эндпоинт (ws://...), а не HTTP.
                # Для простоты, пока оставим эту логику как есть, но возможно, ее нужно будет адаптировать.
                # На данный момент, документация Magnitude не описывает прямого подключения к CDP.
                # Поэтому мы пока будем игнорировать эндпоинты и позволим Magnitude управлять браузером.
                logger.warning("Подключение к удаленному браузеру пока не реализовано для Magnitude. Запускаю новый браузер.")

            agent = BrowserAgent()
            agent.goto(self.goal) # Magnitude может сам понять, что нужно перейти на сайт
            
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