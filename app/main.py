from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(
    title="SmartTask FAQ",
    description="RAG-based FAQ service for SmartTask documentation",
    version="1.0"
)

# Подключение статики
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "smart-task-faq",
        "timestamp": __import__("datetime").datetime.utcnow().isoformat()
    }