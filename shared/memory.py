import chromadb
import requests
import os
from dotenv import load_dotenv
import logging

load_dotenv()
logger = logging.getLogger(__name__)

class RAGMemory:
    def __init__(self, db_path="./chroma_db"):
        self.client = chromadb.PersistentClient(path=db_path)
        
        self.scenarios_collection = self.client.get_or_create_collection(name="successful_scenarios")
        self.failures_collection = self.client.get_or_create_collection(name="failure_knowledge_base")
        
        # --- Новые настройки для API эмбеддингов ---
        self.embedding_endpoint_id = os.getenv("RUNPOD_ENDPOINT_ID_EMBEDDING")
        self.api_key = os.getenv("RUNPOD_API_KEY")
        self.embedding_model_name = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-en-v1.5")

        if not self.embedding_endpoint_id or not self.api_key:
            raise ValueError("RUNPOD_ENDPOINT_ID_EMBEDDING и RUNPOD_API_KEY должны быть установлены в .env")

        self.embedding_api_url = f"https://api.runpod.ai/v2/{self.embedding_endpoint_id}/openai/v1/embeddings"
        logger.info(f"Система памяти RAG инициализирована. Используется API эндпоинт: {self.embedding_api_url}")
    
    def _get_embedding(self, text: str) -> list[float]:
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


    def add_successful_scenario(self, goal: str, steps: list[str]):
        document = f"Цель: {goal}\n" + "\n".join(f"Шаг: {step}" for step in steps)
        doc_id = f"scenario_{self.scenarios_collection.count() + 1}"
        
        embedding = self._get_embedding(document)
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
        
    def add_failure_log(self, error_context: str, attempted_strategy: str, was_successful: bool):
        document = f"Контекст ошибки: {error_context}\nСтратегия: {attempted_strategy}\nУспех: {was_successful}"
        doc_id = f"failure_{self.failures_collection.count() + 1}"
        
        embedding = self._get_embedding(error_context) # Векторизуем именно контекст ошибки
        if not embedding:
            logger.warning(f"Не удалось получить эмбеддинг для лога ошибки. Пропускаю.")
            return

        self.failures_collection.add(
            embeddings=[embedding], documents=[document],
            metadatas=[{"successful": was_successful}], ids=[doc_id]
        )
        logger.info(f"Сохранен лог ошибки с ID {doc_id}")

    def search_similar_failures(self, error_context: str, n_results: int = 1) -> dict:
        query_embedding = self._get_embedding(error_context)
        if not query_embedding:
            return {}
            
        return self.failures_collection.query(
            query_embeddings=[query_embedding], n_results=n_results,
            where={"successful": True} 
        )

rag_memory_instance = RAGMemory() 