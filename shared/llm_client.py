import os
import requests
import json
import time
from dotenv import load_dotenv
import logging

load_dotenv()
logger = logging.getLogger(__name__)

class GemmaClient:
    def __init__(self):
        # --- Конфигурация из переменных окружения ---
        self.gemma_endpoint_id = os.getenv("RUNPOD_ENDPOINT_ID_GEMMA")
        self.api_key = os.getenv("RUNPOD_API_KEY")
        
        if not self.gemma_endpoint_id:
            raise ValueError("RUNPOD_ENDPOINT_ID_GEMMA должен быть установлен в .env файле")
        if not self.api_key:
            raise ValueError("RUNPOD_API_KEY должен быть установлен в .env файле")

        self.base_url = f"https://api.runpod.ai/v2/{self.gemma_endpoint_id}"
        logger.info(f"Клиент Gemma инициализирован. Используется эндпоинт: {self.base_url}")


    def _run_and_poll_task(self, prompt: str) -> dict:
        """
        Реализует логику "Запустить и Опросить" для RunPod API.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # --- Шаг 1: Запуск задачи ---
        run_url = f"{self.base_url}/run"
        run_body = {"input": {"prompt": prompt}}

        try:
            logger.info("Запускаю асинхронную задачу в LLM...")
            run_response = requests.post(run_url, headers=headers, json=run_body, timeout=20)
            run_response.raise_for_status()
            task_info = run_response.json()
            task_id = task_info.get("id")
            if not task_id:
                logger.error(f"Не удалось получить ID задачи от RunPod: {task_info}")
                return {"error": "Не удалось получить ID задачи от RunPod"}
            logger.info(f"Задача успешно запущена с ID: {task_id}")

        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при запуске задачи в LLM API: {e}")
            return {"error": str(e)}

        # --- Шаг 2: Опрос статуса задачи ---
        status_url = f"{self.base_url}/status/{task_id}"
        start_time = time.time()
        timeout = 120  # Максимальное время ожидания в секундах

        while time.time() - start_time < timeout:
            try:
                logger.info(f"Проверяю статус задачи {task_id}...")
                status_response = requests.get(status_url, headers=headers, timeout=20)
                status_response.raise_for_status()
                status_data = status_response.json()
                
                status = status_data.get("status")
                if status == "COMPLETED":
                    logger.info("Задача успешно выполнена!")
                    # Ответ от модели находится в поле 'output'
                    return status_data.get("output", {})
                elif status == "FAILED":
                    logger.error(f"Выполнение задачи {task_id} провалилось: {status_data}")
                    return {"error": "Выполнение задачи провалилось"}
                
                # Если статус IN_QUEUE или IN_PROGRESS, просто ждем
                time.sleep(5) # Пауза между опросами

            except requests.exceptions.RequestException as e:
                logger.error(f"Ошибка при опросе статуса задачи {task_id}: {e}")
                time.sleep(5)

        logger.error(f"Таймаут ожидания выполнения задачи {task_id}.")
        return {"error": "Таймаут ожидания ответа от LLM"}

    def get_next_action(self, goal: str, page_context: dict) -> dict:
        prompt = f"""
        Ты - ИИ ассистент для веб-автоматизации.
        Текущая цель: "{goal}"
        Текущий URL: {page_context.get('url')}
        Проанализируй дерево доступности (accessibility tree) ниже и реши, какое действие нужно совершить.
        Дерево доступности:
        {json.dumps(page_context.get('accessibility_tree'), indent=2, ensure_ascii=False)}
        Верни ТОЛЬКО JSON объект со структурой: {{ "action": "...", "element_id": "...", "text": "...", "reasoning": "..." }}
        """
        return self._run_and_poll_task(prompt)

    def classify_error(self, error_context: str) -> dict:
        prompt = f"""
        Ты - ИИ ассистент для анализа ошибок.
        Контекст ошибки: {error_context}
        Классифицируй ошибку. Верни ТОЛЬКО JSON объект со структурой: {{ "error_type": "...", "reason": "...", "recommended_recovery": "..." }}
        """
        return self._run_and_poll_task(prompt)

    def create_plan_for_goal(self, goal: str) -> dict:
        prompt = f"""
        Ты - ИИ-планировщик.
        Цель: "{goal}"
        Разбей цель на атомарные шаги. Верни ТОЛЬКО JSON объект со структурой: {{ "plan": ["шаг 1", "шаг 2", "..."] }}
        """
        return self._run_and_poll_task(prompt)

# Синглтон экземпляр клиента
llm_client = GemmaClient() 