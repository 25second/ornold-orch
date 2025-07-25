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


    def _run_and_poll_task(self, payload) -> dict:
        """
        Реализует логику "Запустить и Опросить" для RunPod API.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # --- Шаг 1: Запуск задачи ---
        run_url = f"{self.base_url}/run"
        
        # Если передали строку, оборачиваем в нужную структуру
        if isinstance(payload, str):
            run_body = {"input": {"prompt": payload}}
        else:
            # Если передали уже готовый payload, используем как есть
            run_body = payload

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

    def get_next_action(self, goal: str, url: str, marked_html: str, previous_actions: list) -> dict:
        """
        Формирует промпт для LLM, чтобы получить следующее действие.
        """
        prompt = f"""
Ты — продвинутый ИИ-ассистент, управляющий браузером.
Твоя текущая цель: "{goal}".
Ты находишься на странице: {url}.

Вот размеченное содержимое страницы (только body, без script и style), где каждому интерактивному элементу присвоен 'data-ornold-id':
---
{marked_html}
---

Твои последние действия (для контекста): {previous_actions}

Твоя задача — определить **одно** следующее действие для достижения цели.
Доступные действия: "click", "type".
Для действия "type" обязательно укажи "text".
Верни ответ в формате JSON. Пример:
{{"action": "click", "element_id": "15"}}
или
{{"action": "type", "element_id": "23", "text": "my-secret-password"}}

Если цель достигнута или не может быть достигнута с текущими элементами, верни:
{{"action": "finish", "reason": "Цель достигнута"}}
"""
        
        logger.info("Запрос к LLM для получения следующего действия...")
        # logger.debug(f"Промпт для LLM: {prompt}") # Можно раскомментировать для отладки

        return self._run_and_poll_task(prompt)

    def get_next_action_universal(self, goal: str, history: list, perception: dict) -> dict:
        """
        Универсальный мыслительный цикл агента. Определяет следующее действие.
        """
        # Собираем всю инструкцию в один большой промпт, как того требует API.
        full_prompt = f"""
Ты — агент для управления браузером.
Цель: "{goal}"

ДОСТУПНЫЕ ДЕЙСТВИЯ (ТОЛЬКО ЭТИ 5!):
1. {{"action": "think", "text": "...", "reasoning": "..."}}
2. {{"action": "browse", "url": "...", "reasoning": "..."}}  
3. {{"action": "click", "element_id": "...", "reasoning": "..."}}
4. {{"action": "type", "element_id": "...", "text": "...", "reasoning": "..."}}
5. {{"action": "finish", "result": "...", "reasoning": "..."}}

ЗАПРЕЩЕНО: extract_concert_details, extract_event_details, show_popup, или любые другие действия!

История: {history[-3:]}
Состояние: {json.dumps(perception, ensure_ascii=False)}

Ответь ТОЛЬКО JSON одного из 5 действий выше:
"""
        logger.info("Запрос к LLM (формат 'prompt')...")
        
        llm_response = self._run_and_poll_task(full_prompt)

        # 1. Явно обрабатываем ошибку от нашего клиента
        if "error" in llm_response:
            logger.error(f"Ошибка от _run_and_poll_task: {llm_response['error']}")
            return {"action": "think", "text": f"Внутренняя ошибка LLM-клиента: {llm_response['error']}", "reasoning": "LLM-клиент не смог получить ответ от API."}

        # 2. Парсим успешный ответ, структура которого подтверждена тестами.
        if llm_response and isinstance(llm_response, list) and llm_response[0].get('choices'):
            try:
                # Структура ответа: response['output'][0]['choices'][0]['text']
                # _run_and_poll_task возвращает нам `output`, так что начинаем с [0]
                content = llm_response[0]['choices'][0]['text']
                cleaned_content = content.strip().replace("```json", "").replace("```", "")
                parsed_action = json.loads(cleaned_content)
                
                # Проверяем, что действие из разрешенного списка
                allowed_actions = ["think", "browse", "click", "type", "finish"]
                action_type = parsed_action.get("action")
                
                if action_type not in allowed_actions:
                    logger.warning(f"LLM предложил неразрешенное действие '{action_type}'. Заменяю на 'think'.")
                    return {
                        "action": "think", 
                        "text": f"LLM ошибочно предложил действие '{action_type}'. Нужно выбрать из: {allowed_actions}",
                        "reasoning": "Исправляю ошибку LLM"
                    }
                
                return parsed_action
                
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                logger.error(f"Не удалось распарсить JSON из ответа LLM: {e}. Ответ: {content}")
                return {"action": "think", "text": f"Ошибка парсинга ответа от LLM: {content}"}

        logger.warning(f"Получен нестандартный ответ от LLM: {llm_response}")
        return {"action": "think", "text": f"Получен непонятный ответ от LLM: {llm_response}"}


    def execute_prompt(self, prompt: str) -> dict:
        """
        Выполняет простой промпт и возвращает результат.
        """
        logger.info("Запрос к LLM с прямым промптом...")
        return self._run_and_poll_task(prompt)

    def classify_error(self, goal: str, url: str, marked_html: str, failed_action: dict, exception_message: str) -> dict:
        """
        Анализирует контекст ошибки и предлагает стратегию восстановления.
        """
        prompt = f"""
Ты — продвинутый ИИ-аналитик, помогающий веб-агенту восстанавливаться после ошибок.
Агент пытался выполнить цель: "{goal}".

Он находился на странице: {url}
Он пытался выполнить действие: {failed_action}
Но получил Python-исключение: "{exception_message}"

Вот HTML-код страницы, на которой произошла ошибка:
---
{marked_html}
---

Твоя задача — проанализировать ситуацию и предложить лучшую стратегию восстановления.

Возможные типы ошибок:
- "stale_element": Элемент устарел или исчез со страницы.
- "navigation_error": Ошибка при переходе на новую страницу.
- "element_not_found": Элемент не был найден селектором.
- "unexpected_content": На странице неожиданный контент (капча, попап, ошибка 404).
- "login_failed": Неудачная попытка входа в систему.
- "unknown": Другая ошибка.

Возможные стратегии восстановления:
- "retry": Попробовать выполнить то же самое действие еще раз. Может помочь, если ошибка была случайной.
- "refresh": Обновить страницу. Помогает, если элементы "зависли".
- "go_back": Вернуться на предыдущую страницу.
- "human_intervention": Если ты считаешь, что агент не справится сам.

Проанализируй HTML и ошибку и верни ТОЛЬКО JSON-объект с твоим вердиктом.
Пример:
{{"error_type": "stale_element", "recovery_strategy": "refresh"}}
"""
        logger.info("Запрос к LLM для классификации ошибки...")
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