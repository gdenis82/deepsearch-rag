import os
import chromadb
import openai
import uuid
from typing import List, Dict, Tuple, Optional, Any

from chromadb.utils.embedding_functions import (
    openai_embedding_function,
    sentence_transformer_embedding_function,
)
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings
from app.utils import logging, extract_text_from_path

COLLECTION_NAME = "deepsearch_docs"

# Embedding function
if settings.OPENAI_API_KEY and settings.OPENAI_API_KEY.strip():
    embedding_fn = openai_embedding_function.OpenAIEmbeddingFunction(
        api_key_env_var="OPENAI_API_KEY",
        model_name=settings.EMBEDDING_MODEL,
    )
    llm_client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
else:
    # embedding_fn = sentence_transformer_embedding_function.SentenceTransformerEmbeddingFunction(
    #     model_name="all-MiniLM-L6-v2"
    # )
    raise ValueError("OPENAI_API_KEY не задан в настройках.")

class ChromaManager:
    """Класс-менеджер для работы с ChromaDB через AsyncHttpClient.

    Инкапсулирует ленивую инициализацию клиента/коллекции и
    предоставляет асинхронные методы для базовых операций.
    """

    def __init__(self) -> None:
        self._client: Optional[Any] = None
        self._collection: Optional[Any] = None

    async def get_collection(self) -> Any:
        """Ленивая инициализация и возврат коллекции Chroma."""
        if self._collection is not None:
            return self._collection

        try:
            # асинхронный HTTP-клиент удалённого Chroma
            self._client = await chromadb.AsyncHttpClient(
                host=settings.CHROMA_HOST,
                port=int(settings.CHROMA_PORT),
            )
            self._collection = await self._client.get_or_create_collection(
                name=COLLECTION_NAME,
                embedding_function=embedding_fn,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            logging.error(f"Не удалось инициализировать ChromaDB: {e}")
            raise

        return self._collection

    async def count(self) -> int:
        coll = await self.get_collection()
        return await coll.count()

    async def add(self, *, documents: List[str], metadatas: List[Dict], ids: List[str]) -> None:
        coll = await self.get_collection()
        await coll.add(documents=documents, metadatas=metadatas, ids=ids)

    async def query(self, *, query_texts: List[str], n_results: int) -> Dict:
        coll = await self.get_collection()
        return await coll.query(query_texts=query_texts, n_results=n_results)

    async def get_ids_by_source(self, source: str) -> List[str]:
        """Вернуть список id по значению metadata.source.

        Используется для проверки существования и последующего удаления документа.
        """
        coll = await self.get_collection()
        try:
            res = await coll.get(where={"source": source})
            return res.get("ids", []) or []
        except Exception as e:
            logging.error(f"Ошибка чтения из ChromaDB для source='{source}': {e}")
            raise

    async def delete_by_source(self, source: str) -> None:
        """Удалить все элементы коллекции с metadata.source == source."""
        coll = await self.get_collection()
        try:
            await coll.delete(where={"source": source})
        except Exception as e:
            logging.error(f"Ошибка удаления из ChromaDB для source='{source}': {e}")
            raise


_chroma_manager = ChromaManager()


def chunk_text(text: str, source_name: str) -> List[Dict]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=["\n\n", "\n", ". ", "!", "?", " ", ""]
    )
    chunks = splitter.split_text(text)
    return [{"text": chunk, "source": source_name} for chunk in chunks]


async def ingest_documents(doc_dir: str = None, file_paths: Optional[List[str]] = None, force: bool = False) -> Tuple[
    int, int, List[str]]:
    """Добавление документов в Chroma.

    Аргументы:
      - doc_dir: директория для поиска документов (используется, если file_paths не задан).
      - file_paths: список конкретных файлов для загрузки.
      - force: игнорировать проверку пустоты коллекции (при загрузке через API).

    Возвращает:
      - tuple: (кол-во добавленных чанков, кол-во обработанных документов, список имён файлов)
    """
    # Поведение: на старте, если коллекция не пуста - пропускаем
    # Проверка: если коллекция не пуста — пропускаем (если не force и не явные файлы)
    if not force and not file_paths:
        try:
            if await _chroma_manager.count() > 0:
                logging.debug("ChromaDB уже содержит документы — пропускаем.")
                return 0, 0, []
        except Exception as e:
            logging.error(f"Не удалось получить количество документов Chroma: {e}")

    logging.debug("Запуск обработки документов...")
    all_chunks: List[Dict] = []
    sources: List[str] = []

    candidates: List[str] = []
    if file_paths:
        candidates = file_paths
    else:
        if not os.path.isdir(doc_dir):
            logging.debug(f"Директория документов не найдена: {doc_dir}")
            return 0, 0, []
        candidates = [os.path.join(doc_dir, f) for f in os.listdir(doc_dir)]

    supported_ext = {".pdf", ".txt", ".md", ".docx"}
    processed_files: List[str] = []

    for path in candidates:
        filename = os.path.basename(path)
        try:
            if os.path.splitext(filename)[1].lower() not in supported_ext:
                continue
            logging.debug(f"Обработка: {filename}")
            text = extract_text_from_path(path)
            if not text:
                logging.debug(f"Пустой документ: {filename}")
                continue
            chunks = chunk_text(text, filename)
            if not chunks:
                logging.debug(f"Нет чанков после разбиения: {filename}")
                continue
            all_chunks.extend(chunks)
            sources.extend([filename] * len(chunks))
            processed_files.append(filename)
        except Exception as e:
            logging.error(f"Ошибка при обработке {filename}: {e}")

    if not all_chunks:
        logging.debug("Нет данных для инжеста!")
        return 0, 0, []

    texts = [c["text"] for c in all_chunks]
    metadatas = [{"source": c["source"]} for c in all_chunks]

    # Перед добавлением в коллекцию — если документ уже существует, удаляем все, что связано с ним
    # повторная загрузка документа должна привести к его переиндексации
    unique_sources = list(set(processed_files))
    for src in unique_sources:
        try:
            existing_ids = await _chroma_manager.get_ids_by_source(src)
            if existing_ids:
                logging.debug(f"Найдены существующие записи для '{src}' ({len(existing_ids)} шт.) — удаляем перед переиндексацией.")
                await _chroma_manager.delete_by_source(src)
        except Exception as e:
            logging.error(f"Не удалось проверить/очистить существующие записи для '{src}': {e}")

    # Уникальные id, чтобы избежать конфликтов при повторных загрузках
    ids = [f"id_{uuid.uuid4()}" for _ in range(len(texts))]

    await _chroma_manager.add(documents=texts, metadatas=metadatas, ids=ids)
    logging.debug(f"Добавлено {len(texts)} чанков из {len(set(sources))} документов.")
    return len(texts), len(set(processed_files)), processed_files


async def retrieve_context(query: str, k: int = 3) -> List[Dict[str, str]]:
    results = await _chroma_manager.query(query_texts=[query], n_results=k)
    return [
        {
            "text": doc,
            "source": meta.get("source", "unknown")
        }
        for doc, meta in zip(results["documents"][0], results["metadatas"][0])
    ]


async def delete_document_from_rag(filename: str):
    """Удаление документа из векторной базы."""
    try:
        await _chroma_manager.delete_by_source(filename)
        logging.debug(f"Документ '{filename}' удален из ChromaDB.")
    except Exception as e:
        logging.error(f"Ошибка при удалении '{filename}' из ChromaDB: {e}")
        raise e


async def generate_answer(question: str, context_list: List[Dict[str, str]]) -> Tuple[str, List[str], int, int]:
    context_text = "\n\n".join(
        f"[{i + 1}] {c['text']}" for i, c in enumerate(context_list)
    )
    sources = list({c["source"] for c in context_list})

    prompt = f"""

    Контекст:
    {context_text}
    
    Вопрос: {question}
    
    Ответ:"""

    try:
        response = await llm_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": settings.ANSWER_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1024,
            temperature=0.0,
        )
        answer = response.choices[0].message.content
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
    except Exception as e:
        raise RuntimeError(f"OpenAI error: {e}")

    return answer, sources, input_tokens, output_tokens
