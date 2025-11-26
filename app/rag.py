import os
import chromadb
from typing import List, Dict, Tuple, Optional

from anthropic.types import MessageParam
from chromadb.utils.embedding_functions import (openai_embedding_function,
                                                sentence_transformer_embedding_function)
from langchain_text_splitters import RecursiveCharacterTextSplitter

import anthropic
import openai
from openai.types.chat import ChatCompletionMessageParam

from app.core.config import settings
from app.utils import extract_text_from_pdf, logging, extract_text_from_path

COLLECTION_NAME = "smarttask_docs"

# Инициализация Chroma
client = chromadb.PersistentClient(path=settings.CHROMA_PATH)

# Embedding function
if settings.OPENAI_API_KEY and settings.OPENAI_API_KEY.strip():
    embedding_fn = openai_embedding_function.OpenAIEmbeddingFunction(
        api_key=settings.OPENAI_API_KEY,
        model_name=settings.EMBEDDING_MODEL,

    )
else:
    embedding_fn = sentence_transformer_embedding_function.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )

collection = client.get_or_create_collection(
    name=COLLECTION_NAME,
    embedding_function=embedding_fn,
    metadata={"hnsw:space": "cosine"}
)


def chunk_text(text: str, source_name: str) -> List[Dict]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=["\n\n", "\n", ". ", "!", "?", " ", ""]
    )
    chunks = splitter.split_text(text)
    return [{"text": chunk, "source": source_name} for chunk in chunks]




def ingest_documents(doc_dir: str = None, file_paths: Optional[List[str]] = None, force: bool = False) -> Tuple[int, int, List[str]]:
    """Добавление документов в Chroma.

    Аргументы:
      - doc_dir: директория для поиска документов (используется, если file_paths не задан).
      - file_paths: список конкретных файлов для загрузки.
      - force: игнорировать проверку пустоты коллекции (при загрузке через API).

    Возвращает:
      - кортеж: (кол-во добавленных чанков, кол-во обработанных документов, список имён файлов)
    """
    # Поведение: на старте, если коллекция не пуста - пропускаем
    if not force and not file_paths and collection.count() > 0:
        logging.debug("ChromaDB уже содержит документы — пропускаем.")
        return 0, 0, []

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

    supported_ext = {".pdf", ".txt", ".md"}
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
    # Уникальные id, чтобы избежать конфликтов при повторных загрузках
    import uuid
    ids = [f"id_{uuid.uuid4()}" for _ in range(len(texts))]

    collection.add(
        documents=texts,
        metadatas=metadatas,
        ids=ids
    )
    logging.debug(f"Добавлено {len(texts)} чанков из {len(set(sources))} документов.")
    return len(texts), len(set(processed_files)), processed_files

def retrieve_context(query: str, k: int = 3) -> List[Dict[str, str]]:
    results = collection.query(
        query_texts=[query],
        n_results=k
    )
    return [
        {
            "text": doc,
            "source": meta.get("source", "unknown")
        }
        for doc, meta in zip(results["documents"][0], results["metadatas"][0])
    ]

def generate_answer(question: str, context_list: List[Dict[str, str]]) -> Tuple[str, List[str], int, int]:
    context_text = "\n\n".join(
        f"[{i+1}] {c['text']}" for i, c in enumerate(context_list)
    )
    sources = list({c["source"] for c in context_list})

    prompt = f"""

    Контекст:
    {context_text}
    
    Вопрос: {question}
    
    Ответ:"""

    if settings.ANTHROPIC_API_KEY and settings.ANTHROPIC_API_KEY.strip():
        llm_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        try:
            messages: list[MessageParam] = [{"role": "system", "content": settings.ANSWER_PROMPT},
                                            {"role": "user", "content": prompt}]
            model = "claude-3-5-sonnet-20241022"
            response = llm_client.messages.create(
                model=model,
                messages=messages,
                max_tokens=1024,
                temperature=0.0,
            )
            answer = response.content[0].text

            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
        except Exception as e:
            raise RuntimeError(f"Anthropic error: {e}")
    elif settings.OPENAI_API_KEY and settings.OPENAI_API_KEY.strip():
        llm_client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        try:

            response = llm_client.chat.completions.create(
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
    else:
        raise ValueError("Ни ANTHROPIC_API_KEY, ни OPENAI_API_KEY не заданы")

    return answer, sources, input_tokens, output_tokens