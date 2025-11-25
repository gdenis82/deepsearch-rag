import logging

import redis
import json
import hashlib
from typing import Optional, Dict, Any

from app.core.config import settings

logger = logging.getLogger(__name__)

redis_client = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2
)

def hash_query(query: str) -> str:
    return hashlib.md5(query.lower().strip().encode("utf-8")).hexdigest()

def get_cache(key: str) -> Optional[Dict[str, Any]]:
    try:
        cached = redis_client.get(key)
        return json.loads(cached) if cached else None
    except Exception as e:
        logger.error(f"Redis get failed: {e}")
        return None

def set_cache(key: str, value: Dict[str, Any], ttl: int = 3600):
    try:
        redis_client.setex(key, ttl, json.dumps(value, ensure_ascii=False))
    except Exception as e:
        logger.error(f"Redis set failed: {e}")