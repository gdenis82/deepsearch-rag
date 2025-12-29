import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import hash_query, get_cache, set_cache
from app.core.config import settings
from app.db.session import get_async_session
from app.models.query_logs import QueryLog
from app.rag import retrieve_context, generate_answer, ingest_documents, delete_document_from_rag
from app.schemas.common import QuestionRequest, PromptUpdate
from app.utils import logger, Timer

api_router = APIRouter()


@api_router.get("/prompt")
async def get_prompt():
    """Получение текущего системного промпта."""
    return {"prompt": settings.ANSWER_PROMPT}


@api_router.post("/prompt")
async def update_prompt(request: PromptUpdate):
    """Обновление системного промпта."""
    new_prompt = request.prompt
    settings.ANSWER_PROMPT = new_prompt

    # Сохраняем в файл, если путь настроен
    prompt_path = os.getenv("ANSWER_PROMPT_PATH")
    if prompt_path:
        # Пытаемся определить абсолютный путь аналогично Settings.__init__
        if not os.path.isabs(prompt_path):
            core_dir = os.path.dirname(__file__)
            app_dir = os.path.abspath(os.path.join(core_dir, ".."))
            project_root = os.path.abspath(os.path.join(app_dir, ".."))
            prompt_path = os.path.abspath(os.path.join(project_root, prompt_path))

        try:
            with open(prompt_path, "w", encoding="utf-8") as f:
                f.write(new_prompt)
            logger.info(f"System prompt updated and saved to {prompt_path}")
        except Exception as e:
            logger.error(f"Failed to save prompt to file: {e}")
            # Мы все равно обновили его в памяти, но сообщим об ошибке сохранения если нужно
            # В данном случае просто залогируем

    return {"status": "success", "prompt": settings.ANSWER_PROMPT}


@api_router.get("/health")
async def health(db: AsyncSession = Depends(get_async_session)):
    """Проверка состояния сервиса и базы данных."""
    try:
        await db.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "service": "smart-task-faq",
            "timestamp": __import__("datetime").datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}




@api_router.post("/ask")
async def ask_question(request: QuestionRequest, db: AsyncSession = Depends(get_async_session)):
    """Обработка вопроса от пользователя с использованием RAG."""
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is empty")

    with Timer() as timer:
        cache_key = await hash_query(question)
        cached = await get_cache(cache_key)
        if cached:
            if "response_time_ms" in cached:
                cached["response_time_ms"] = int(timer.elapsed)
            logger.debug(f"Cache hit for: {question[:50]}...")
            return cached

    with Timer() as timer:
        try:
            context = await retrieve_context(question, k=3)
            answer, sources, in_toks, out_toks = await generate_answer(question, context)

            # Лог в БД
            log_entry = QueryLog(
                question=question,
                answer=answer,
                sources=",".join(sources) if sources else "",
                input_tokens=in_toks,
                output_tokens=out_toks,
                response_time_ms=int(timer.elapsed)
            )
            db.add(log_entry)
            try:
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error(f"Error saving query log: {e}", exc_info=True)
                raise e

            result = {
                "answer": answer,
                "sources": sources,
                "tokens": {
                    "input": in_toks,
                    "output": out_toks
                },
                "response_time_ms": int(timer.elapsed)
            }

            await set_cache(cache_key, result)
            logger.debug(
                f"Q: {question[:50]}... | Time: {timer.elapsed:.0f}ms | "
                f"Tokens: {in_toks}+{out_toks} | Sources: {sources}"
            )
            return result

        except Exception as e:
            logger.error(f"Error processing '{question[:30]}...': {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")


@api_router.post("/documents")
async def upload_documents(files: list[UploadFile] = File(...)):
    """Загрузка документов в базу знаний (поддержка: txt, md, pdf)."""
    import os
    saved_paths = []
    doc_dir = settings.DOCUMENTS_PATH
    os.makedirs(doc_dir, exist_ok=True)

    if not files:
        raise HTTPException(status_code=400, detail="Нет файлов для загрузки")

    # Сохранение загруженных файлов в директорию документов
    for f in files:
        filename = os.path.basename(f.filename)
        if not filename:
            continue
        target_path = os.path.join(doc_dir, filename)
        content = await f.read()
        with open(target_path, "wb") as out:
            out.write(content)
        saved_paths.append(target_path)

    if not saved_paths:
        raise HTTPException(status_code=400, detail="Не удалось сохранить файлы")

    try:
        chunks, docs_count, processed = await ingest_documents(doc_dir=doc_dir, file_paths=saved_paths, force=True)
    except Exception as e:
        logger.error(f"Ошибка инжеста документов: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка инжеста: {str(e)}")

    return {
        "added_chunks": chunks,
        "documents_count": docs_count,
        "processed_files": processed,
    }


@api_router.get("/documents")
async def list_documents(page: int = 1, size: int = 10):
    """Получение списка загруженных документов с пагинацией."""
    import os
    import datetime
    doc_dir = settings.DOCUMENTS_PATH
    if not os.path.exists(doc_dir):
        return {"total": 0, "page": page, "size": size, "items": []}

    all_documents = []
    for filename in os.listdir(doc_dir):
        file_path = os.path.join(doc_dir, filename)
        if os.path.isfile(file_path):
            stat = os.stat(file_path)
            all_documents.append({
                "name": filename,
                "upload_date": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "size": stat.st_size
            })

    # Сортировка по дате (сначала новые)
    all_documents.sort(key=lambda x: x["upload_date"], reverse=True)

    total = len(all_documents)
    start = (page - 1) * size
    end = start + size
    items = all_documents[start:end]

    return {
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size,
        "items": items
    }


@api_router.delete("/documents/{filename}")
async def delete_document(filename: str):
    """Удаление документа из системы и из RAG."""
    import os
    doc_path = os.path.join(settings.DOCUMENTS_PATH, filename)
    
    # 1. Удаляем из RAG
    try:
        await delete_document_from_rag(filename)
    except Exception as e:
        logger.error(f"Ошибка при удалении '{filename}' из RAG: {e}")
        # Продолжаем удаление файла, даже если в RAG возникла ошибка (возможно его там уже нет)

    # 2. Удаляем файл
    if os.path.exists(doc_path):
        try:
            os.remove(doc_path)
            logger.info(f"Файл {filename} удален.")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Не удалось удалить файл: {str(e)}")
    else:
        # Если файла нет на диске, но мы дошли сюда, возможно это ошибка, но для надежности вернем success если он удален из RAG
        pass

    return {"status": "success", "message": f"Документ {filename} удален"}