import asyncio
from playwright.async_api import async_playwright, Browser, Page
import random
from shared.memory import rag_memory_instance
import redis
import json
import logging
from shared.llm_client import llm_client
from shared.dom_processor import mark_interactive_elements
from typing import Optional
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Получаем хосты из переменных окружения
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "localhost")

redis_client = redis.Redis(host=REDIS_HOST, port=6379, db=0, decode_responses=True)

class SessionAgent:
    def __init__(self, task_id: str, browser_endpoint_url: str):
        self.task_id = task_id
        self.browser_endpoint_url = browser_endpoint_url
        self.status = "idle"
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.action_history: list[dict] = []
        logger.info(f"Агент для эндпоинта {self.browser_endpoint_url} (задача {self.task_id}) создан.")

    async def connect_to_browser(self):
        logger.info(f"Агент {self.task_id}: Подключаюсь к браузеру по эндпоинту {self.browser_endpoint_url}...")
        try:
            p = await async_playwright().start()
            self.browser = await p.chromium.connect_over_cdp(self.browser_endpoint_url)
            self.page = self.browser.contexts[0].pages[0]
            logger.info(f"Агент {self.task_id}: Успешно подключился. Текущая страница: {self.page.url}")
            return True
        except Exception as e:
            logger.error(f"Агент {self.task_id}: Не удалось подключиться к браузеру по эндпоинту {self.browser_endpoint_url}. Ошибка: {e}")
            return False

    async def get_perception_data(self) -> dict:
        """
        Получает информацию со страницы (URL, размеченный HTML)
        """
        if not self.page:
            return {}
        
        raw_html = await self.page.content()
        marked_html = mark_interactive_elements(raw_html)

        return {
            "url": self.page.url,
            "marked_html": marked_html,
        }

    async def _decide_next_action(self, step_goal: str, perception_data: dict) -> dict:
        """
        Принимает решение о следующем действии, используя LLM.
        """
        logger.info(f"Принимаю решение для шага '{step_goal}'...")

        # Вызов реального клиента (теперь синхронный)
        llm_response = llm_client.get_next_action(
            goal=step_goal,
            url=perception_data.get("url"),
            marked_html=perception_data.get("marked_html"),
            previous_actions=self.action_history
        )
        
        logger.info(f"Решение от LLM принято: {llm_response}")
        return llm_response

    async def _verify_state_after_action(self, action: dict) -> bool:
        """
        Проверяет состояние страницы после действия на предмет аномалий.
        Возвращает True, если все в порядке, и False, если обнаружена аномалия.
        """
        if not self.page:
            return False

        # Простая проверка на слова-маркеры ошибок
        error_keywords = ["error", "ошибка", "fail", "неверный", "invalid"]
        page_text = await self.page.content()
        page_lower = page_text.lower()

        for keyword in error_keywords:
            if keyword in page_lower:
                error_context = f"Обнаружено ключевое слово ошибки: '{keyword}' после действия {action}"
                print(error_context)
                rag_memory_instance.add_failure_log(error_context, str(action), False)
                return False
        
        # В будущем здесь будут более сложные проверки (HTTP-статусы, модальные окна и т.д.)
        print("Проверка после действия: Аномалий не обнаружено.")
        return True

    async def _classify_anomaly(self, error_context: str) -> dict:
        """
        Отправляет контекст аномалии в LLM для классификации.
        """
        logger.info(f"Классифицирую аномалию: '{error_context[:100]}...'")
        # Вызов реального клиента (теперь синхронный)
        classification_result = llm_client.classify_error(error_context)
        return classification_result


    async def _start_recovery_protocol(self, error_context: str):
        """
        Запускает протокол восстановления после обнаружения аномалии.
        """
        classification = await self._classify_anomaly(error_context)
        print(f"Агент {self.task_id}: Аномалия классифицирована: {classification}")

        recovery_strategy = classification.get("recommended_recovery")
        
        print(f"Запускаю стратегию восстановления: '{recovery_strategy}'...")

        if recovery_strategy == "micro_rollback":
            last_action = self.action_history[-1] if self.action_history else None
            if last_action:
                print(f"Выполняю 'микро-откат': повторяю действие {last_action}")
                # Повторяем действие и снова проверяем состояние
                await self._execute_action(last_action)
                if not await self._verify_state_after_action(last_action):
                    print("Микро-откат не помог.")
                    await self._request_human_intervention("Микро-откат не помог.", last_action)
                else:
                    print("Микро-откат прошел успешно!")
                    # Здесь нужно будет придумать, как вернуться в основной цикл
            else:
                print("Не могу выполнить микро-откат: история действий пуста.")
        
        elif recovery_strategy == "step_rollback":
            print("Стратегия 'шаг-откат' пока не реализована.")
        
        elif recovery_strategy == "session_rollback":
            print("Стратегия 'сессионный откат' пока не реализована.")
            await self._request_human_intervention("Требуется сессионный откат.", self.action_history[-1])

    async def _request_human_intervention(self, reason: str, failed_action: dict | None = None):
        """
        Помечает задачу как требующую вмешательства человека.
        Сохраняет контекст для возобновления.
        """
        logger.warning(f"Агент {self.task_id}: Запрашиваю вмешательство человека. Причина: {reason}")
        
        task_json = redis_client.get(f"task:{self.task_id}")
        if task_json:
            task_data = json.loads(task_json)
            task_data['status'] = 'human_intervention_required'
            task_data['status_reason'] = reason
            
            # Добавляем в контекст URL, чтобы оператор знал, с каким браузером работать
            context = failed_action or {}
            context['browser_endpoint_url'] = self.browser_endpoint_url
            task_data['failed_action_context'] = context
            
            redis_client.set(f"task:{self.task_id}", json.dumps(task_data))


    async def _execute_action(self, action: dict):
        if not self.page:
            logger.error("Невозможно выполнить действие: страница не найдена.")
            return

        action_type = action.get("action")
        # Теперь element_id - это наш надежный 'data-ornold-id'
        element_id = action.get("element_id")
        
        logger.info(f"Агент {self.task_id}: Подготовка к действию '{action_type}' на элементе с ID '{element_id}'")

        # Формируем надежный селектор
        selector = f"[data-ornold-id='{element_id}']"
        
        try:
            if action_type == "click":
                await self._human_like_click(selector)
            elif action_type == "type":
                text_to_type = action.get("text")
                if text_to_type is None:
                    logger.error(f"Действие 'type' для элемента {selector} не содержит текста.")
                    return
                await self._human_like_type(selector, text_to_type)
            else:
                logger.error(f"Агент {self.task_id}: Неизвестное действие '{action_type}'")
                return # Возвращаемся, чтобы не добавлять невалидное действие в историю

            # Добавляем успешно ВЫПОЛНЕННОЕ действие в историю
            self.action_history.append(action)
            logger.info(f"Действие '{action_type}' на элементе {selector} успешно выполнено.")
        except Exception as e:
            logger.error(f"Ошибка при выполнении действия '{action_type}' на элементе {selector}: {e}")
            # Ошибка будет обработана в цикле run_task через _verify_state_after_action
            raise

    async def _human_like_click(self, selector: str):
        """
        Кликает на элемент, имитируя человеческое поведение.
        """
        if not self.page:
            print("Ошибка: страница не найдена.")
            return

        print(f"Имитация 'человечного' клика на '{selector}'...")
        try:
            # Движение мыши к элементу. Playwright делает это достаточно плавно.
            # Для большей реалистичности можно было бы использовать page.mouse.move
            # с промежуточными точками, но click() с опциями - хороший старт.
            await self.page.click(
                selector,
                delay=random.uniform(50, 150), # Задержка между mousedown и mouseup
                button='left',
                click_count=1
            )
            print("Кликнул!")
        except Exception as e:
            error_context = f"Не удалось кликнуть на '{selector}': {e}"
            print(error_context)
            rag_memory_instance.add_failure_log(error_context, "просто кликнуть", False)
            # Здесь в будущем будет запускаться механизм восстановления

    async def _human_like_type(self, selector: str, text: str):
        """
        Печатает текст в элемент посимвольно, как человек.
        """
        if not self.page:
            print("Ошибка: страница не найдена.")
            return

        print(f"Имитация 'человечного' ввода текста '{text}' в '{selector}'...")
        try:
            # Сначала кликаем, чтобы сфокусироваться
            await self._human_like_click(selector)
            
            # Playwright умеет имитировать задержки, но сделаем это вручную для полного контроля
            element = self.page.locator(selector)
            for char in text:
                await element.press(char, delay=random.uniform(50, 200))

            print("Напечатал!")
        except Exception as e:
            error_context = f"Не удалось напечатать в '{selector}': {e}"
            print(error_context)
            rag_memory_instance.add_failure_log(error_context, "кликнуть и печатать", False)
            # Здесь в будущем будет запускаться механизм восстановления

    async def run_task(self, plan: list[str]):
        """
        Запускает выполнение плана для этого сессионного агента.
        """
        self.status = "running"
        logger.info(f"Агент для эндпоинта {self.browser_endpoint_url} начинает выполнение плана: {plan}")
        
        if not self.browser or not self.page:
            is_connected = await self.connect_to_browser()
            if not is_connected:
                self.status = "failed"
                return

        for step in plan:
            logger.info(f"--- Агент (Эндпоинт: {self.browser_endpoint_url}): Выполняю шаг '{step}' ---")
            
            perception_data = await self.get_perception_data()
            if perception_data:
                logger.info(f"URL: {perception_data.get('url')}")
            else:
                logger.warning("Не удалось получить данные восприятия (perception data).")
                await self._request_human_intervention("Не удалось получить данные со страницы, возможно, она закрыта.")
                break

            action = await self._decide_next_action(step, perception_data)

            try:
                # 3. Выполнение
                await self._execute_action(action)
                
                # 4. Верификация (базовая)
                # TODO: Добавить более сложную верификацию
                
            except Exception as e:
                logger.error(f"Агент (Эндпоинт: {self.browser_endpoint_url}): Произошла ошибка при выполнении шага '{step}'. Ошибка: {e}")
                
                # --- Начало протокола восстановления ---
                logger.info("--- ЗАПУСК ПРОТОКОЛА ВОССТАНОВЛЕНИЯ ---")
                error_perception_data = await self.get_perception_data()
                error_url = error_perception_data.get("url", "")
                error_html = error_perception_data.get("marked_html", "")

                # 1. Поиск в базе знаний похожих ошибок
                similar_failures = await rag_memory_instance.search_similar_failures(
                    goal=step, url=error_url, failed_action=action, exception_message=str(e)
                )

                strategy = None
                # Если нашли очень похожую ошибку, используем проверенную стратегию
                if similar_failures and similar_failures[0][1] < 0.2: # 0.2 - порог сходства
                    strategy = similar_failures[0][0].get('recovery_strategy')
                    logger.info(f"Найдено решение в базе знаний! Применяю стратегию: '{strategy}'")
                
                # 2. Если в базе знаний нет решения, обращаемся к LLM
                if not strategy:
                    logger.info("В базе знаний решений не найдено, обращаюсь к LLM для выработки стратегии.")
                    classification = await llm_client.classify_error(
                        goal=step,
                        url=error_url,
                        marked_html=error_html,
                        failed_action=action,
                        exception_message=str(e)
                    )
                    logger.warning(f"Вердикт LLM по ошибке: {classification}")
                    strategy = classification.get("recovery_strategy")

                # 3. Применение стратегии и обучение
                recovery_successful = False
                if strategy == "refresh":
                    logger.info("Стратегия восстановления: Обновляю страницу.")
                    if self.page: await self.page.reload()
                    recovery_successful = True
                elif strategy == "go_back":
                    logger.info("Стратегия восстановления: Возвращаюсь назад.")
                    if self.page: await self.page.go_back()
                    recovery_successful = True
                elif strategy == "retry":
                    logger.info("Стратегия восстановления: Повторяю последнее действие.")
                    recovery_successful = True # Действие будет повторено на следующей итерации
                else: # "human_intervention" или неизвестная стратегия
                    logger.error("Стратегия восстановления: Требуется вмешательство человека.")
                    await self._request_human_intervention(f"Агент не смог выработать стратегию. Последний вердикт: {strategy}")
                    break
                
                # 4. Если восстановление было успешным, запоминаем этот опыт
                if recovery_successful and strategy:
                    logger.info(f"Восстановление прошло успешно. Сохраняю опыт в базу знаний.")
                    await rag_memory_instance.add_failure_log(
                        goal=step, url=error_url, failed_action=action, 
                        exception_message=str(e), recovery_strategy=strategy
                    )
                
                # Если стратегия была "retry", просто переходим к следующей итерации
                if strategy == "retry":
                    continue

            # Если мы дошли сюда, значит шаг (или его восстановление) прошел успешно
            logger.info(f"--- Агент (Эндпоинт: {self.browser_endpoint_url}): Шаг '{step}' успешно завершен ---")


        self.status = "finished"
        logger.info(f"Агент {self.task_id} завершил выполнение плана.")

# --- Пример использования (для тестирования) ---
async def main():
    # Тестовый запуск SessionAgent (требует реального эндпоинта)
    # TEST_URL = "wss://your-tunnel.ngrok.io" 
    # agent = SessionAgent(task_id="test_task_id", browser_endpoint_url=TEST_URL)
    # await agent.run_task(["Шаг 1: Проверить подключение"])
    pass

if __name__ == "__main__":
    asyncio.run(main()) 