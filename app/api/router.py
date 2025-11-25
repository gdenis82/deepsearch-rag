from fastapi import APIRouter

from app.api.endpoints import ask
api_router = APIRouter()

api_router.include_router(ask.router, prefix="/ask", tags=["ask"])