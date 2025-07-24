import chromadb
import requests
import os
from dotenv import load_dotenv
import logging
import asyncio
import json
import hashlib

load_dotenv()
logger = logging.getLogger(__name__)

class RAGMemory:
    def __init__(self, db_path="./chroma_db"):
        self.client = chromadb.PersistentClient(path=db_path)
        
        # Коллекция для успешных сценариев (как было)
        self.scenarios_collection = self.client.get_or_create_collection(
            name="successful_scenarios",
            metadata={"hnsw:space": "cosine"} 
        )
        
        # Новая коллекция для базы знаний по ошибкам
        self.failures_collection = self.client.get_or_create_collection(
            name="failure_knowledge_base",
            metadata={"hnsw:space": "cosine"}
        )
        
        logger.info("RAG Memory инициализирована с коллекциями 'successful_scenarios' и 'failure_knowledge_base'")

        # --- Новые настройки для API эмбеддингов ---
        self.embedding_endpoint_id = os.getenv("RUNPOD_ENDPOINT_ID_EMBEDDING")
        self.api_key = os.getenv("RUNPOD_API_KEY")
        self.embedding_model_name = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-en-v1.5")

        if not self.embedding_endpoint_id or not self.api_key:
            raise ValueError("RUNPOD_ENDPOINT_ID_EMBEDDING и RUNPOD_API_KEY должны быть установлены в .env")

        self.embedding_api_url = f"https://api.runpod.ai/v2/{self.embedding_endpoint_id}/openai/v1/embeddings"
        logger.info(f"Система памяти RAG инициализирована. Используется API эндпоинт: {self.embedding_api_url}")
    
    async def _get_embedding(self, text: str) -> list[float]:
        """Получает векторное представление текста через API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        body = {
            "model": self.embedding_model_name,
            "input": text
        }
        try:
            response = requests.post(self.embedding_api_url, headers=headers, json=body, timeout=30)
            response.raise_for_status()
            result = response.json()
            # API возвращает список эмбеддингов, нам нужен первый (и единственный)
            if result.get("data") and len(result["data"]) > 0:
                return result["data"][0]["embedding"]
            else:
                logger.error(f"API эмбеддингов вернуло неожиданный ответ: {result}")
                return []
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при запросе к API эмбеддингов: {e}")
            return []


    async def add_successful_scenario(self, goal: str, actions: list[dict]):
        document = f"Цель: {goal}\n" + "\n".join(f"Шаг: {json.dumps(step)}" for step in actions)
        doc_id = f"scenario_{self.scenarios_collection.count() + 1}"
        
        embedding = await self._get_embedding(document)
        if not embedding:
            logger.warning(f"Не удалось получить эмбеддинг для успешного сценария '{goal}'. Пропускаю.")
            return

        self.scenarios_collection.add(
            embeddings=[embedding], documents=[document],
            metadatas=[{"goal": goal}], ids=[doc_id]
        )
        logger.info(f"Сохранен успешный сценарий '{goal}' с ID {doc_id}")

    def search_similar_scenarios(self, query: str, n_results: int = 1) -> dict:
        query_embedding = self._get_embedding(query)
        if not query_embedding:
            logger.warning(f"Не удалось получить эмбеддинг для поискового запроса '{query}'. Возвращаю пустой результат.")
            return {}
            
        return self.scenarios_collection.query(
            query_embeddings=[query_embedding], n_results=n_results
        )
        
    async def add_failure_log(self, goal: str, url: str, failed_action: dict, exception_message: str, recovery_strategy: str):
        """
        Сохраняет в базу знаний запись о провале и успешной стратегии восстановления.
        """
        # Создаем подробное текстовое описание проблемы
        error_context_text = f"Цель: {goal}. URL: {url}. Действие: {json.dumps(failed_action)}. Ошибка: {exception_message}"
        
        embedding = await self._get_embedding(error_context_text)
        
        # ID будет хэшем от контекста, чтобы избежать дубликатов
        doc_id = hashlib.sha256(error_context_text.encode()).hexdigest()
        
        logger.info(f"Добавляю запись об ошибке в базу знаний. ID: {doc_id}")
        
        self.failures_collection.add(
            documents=[error_context_text],
            metadatas=[{"recovery_strategy": recovery_strategy}],
            embeddings=[embedding],
            ids=[doc_id]
        )

    async def search_similar_failures(self, goal: str, url: str, failed_action: dict, exception_message: str, n_results: int = 1) -> list:
        """
        Ищет в базе знаний похожие ошибки и возвращает проверенные стратегии восстановления.
        """
        error_context_text = f"Цель: {goal}. URL: {url}. Действие: {json.dumps(failed_action)}. Ошибка: {exception_message}"
        embedding = await self._get_embedding(error_context_text)
        
        results = self.failures_collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            include=["metadatas", "distances"]
        )
        logger.info(f"Поиск похожих ошибок в базе знаний нашел: {results}")
        
        # Возвращаем метаданные (где хранится стратегия) и расстояние до запроса
        return list(zip(results.get('metadatas', [[]])[0], results.get('distances', [[]])[0]))


rag_memory_instance = RAGMemory()

async def main():
    # --- Тестирование новой логики ошибок ---
    print("\n--- Тестирование памяти на ошибках ---")
    test_action = {"action": "click", "element_id": "login_button"}
    
    # Добавляем запись об ошибке
    await rag_memory_instance.add_failure_log(
        goal="Войти в систему",
        url="https://example.com/login",
        failed_action=test_action,
        exception_message="TimeoutError: 30000ms exceeded",
        recovery_strategy="refresh"
    )
    
    # Ищем похожую ошибку
    similar = await rag_memory_instance.search_similar_failures(
        goal="Войти в систему",
        url="https://example.com/login",
        failed_action=test_action,
        exception_message="TimeoutError: waiting for selector", # немного другая ошибка, но контекст тот же
        n_results=1
    )
    
    if similar:
        print(f"Найдена похожая ошибка. Рекомендованная стратегия: {similar[0][0]['recovery_strategy']} (Сходство: {1 - similar[0][1]:.2f})")
    else:
        print("Похожих ошибок не найдено.")


if __name__ == "__main__":
    asyncio.run(main()) 