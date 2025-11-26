from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.cache import hash_query, get_cache, set_cache
from app.core.config import settings
from app.db.session import get_db
from app.models.query_logs import QueryLog
from app.rag import retrieve_context, generate_answer, ingest_documents
from app.schemas.schemas import QuestionRequest
from app.utils import logger, Timer

api_router = APIRouter()


@api_router.get("/health")
async def health(db: Session = Depends(get_db)):
    """Проверка состояния сервиса и базы данных."""
    try:
        db.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "service": "smart-task-faq",
            "timestamp": __import__("datetime").datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}




@api_router.post("/ask")
async def ask_question(request: QuestionRequest, db: Session = Depends(get_db)):
    """Обработка вопроса от пользователя с использованием RAG."""
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is empty")

    with Timer() as timer:
        cache_key = hash_query(question)
        cached = get_cache(cache_key)
        if cached:
            if "response_time_ms" in cached:
                cached["response_time_ms"] = int(timer.elapsed)
            logger.debug(f"Cache hit for: {question[:50]}...")
            return cached

    with Timer() as timer:
        try:
            context = retrieve_context(question, k=3)
            answer, sources, in_toks, out_toks = generate_answer(question, context)

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
            db.commit()

            result = {
                "answer": answer,
                "sources": sources,
                "tokens": {
                    "input": in_toks,
                    "output": out_toks
                },
                "response_time_ms": int(timer.elapsed)
            }

            set_cache(cache_key, result)
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
        chunks, docs_count, processed = ingest_documents(doc_dir=doc_dir, file_paths=saved_paths, force=True)
    except Exception as e:
        logger.error(f"Ошибка инжеста документов: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка инжеста: {str(e)}")

    return {
        "added_chunks": chunks,
        "documents_count": docs_count,
        "processed_files": processed,
    }