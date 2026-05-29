# app/queue_local.py
import logging
import redis.asyncio as redis
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

QUEUE_NAME = "dropbox_tasks"
VISITED_SET = "visited_folders"  # Nuestro escudo antiduplicados

async def get_redis():
    return redis.from_url(settings.redis_url)

async def push_task(path: str):
    """Encola una tarea SOLO si no ha sido procesada/encolada antes."""
    r = await get_redis()
    
    # sadd devuelve 1 si es nuevo, 0 si ya existía
    is_new = await r.sadd(VISITED_SET, path.lower())
    
    if is_new:
        await r.lpush(QUEUE_NAME, path)
        logger.debug(f"📥 Encolado en Redis: {path}")
    else:
        logger.debug(f"⏩ Duplicado bloqueado por Redis: {path}")
        
    await r.aclose()

async def pop_task() -> str | None:
    """Extrae una tarea de la cola (espera si está vacía)."""
    r = await get_redis()
    # Espera hasta 5 segundos por una tarea
    result = await r.brpop(QUEUE_NAME, timeout=5)
    await r.aclose()
    
    if result:
        return result[1].decode('utf-8')
    return None