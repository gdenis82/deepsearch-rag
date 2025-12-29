from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings

@asynccontextmanager
async def lifespan(fast_app: FastAPI):
    # Startup выполняется при запуске приложения
    from app.rag import ingest_documents
    await ingest_documents(doc_dir=settings.DOCUMENTS_PATH)
    yield
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="RAG-based service for DeepSearch documentation",
    version="1.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# Set up CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(settings.BACKEND_CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Apply static files mount
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/docs_files", StaticFiles(directory=settings.DOCUMENTS_PATH), name="docs_files")

# Include the API router
# Versioned API (v1)
app.include_router(api_router, prefix=settings.API_V1_STR)



@app.get("/")
async def root():
    # Перенаправляем на статическую страницу index.html
    return RedirectResponse(url="/static/index.html")

