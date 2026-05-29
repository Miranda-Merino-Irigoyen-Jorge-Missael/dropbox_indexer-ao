# app/main_local.py
import asyncio
import os
import logging
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.queue_local import push_task, pop_task
from app.services.crawler import process_folder_task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODE = os.getenv("MODE", "WORKER")

async def migrate_pending_to_redis():
    """Mueve las tareas que quedaron pendientes en SQL hacia la cola de Redis."""
    async with AsyncSessionLocal() as session:
        # 1. Leer tareas pendientes
        result = await session.execute(text("SELECT path FROM pending_requests"))
        pendientes = result.scalars().all()
        
        if pendientes:
            logger.info(f"📥 Migrando {len(pendientes)} tareas de SQL a Redis...")
            for path in pendientes:
                await push_task(path)
            
            # 2. Limpiar la tabla de forma segura (Antichoque)
            try:
                await session.execute(text("TRUNCATE TABLE pending_requests"))
                await session.commit()
                logger.info("✅ Migración completada. Tabla SQL limpiada.")
            except Exception as e:
                # Si falla (ej. por Deadlock), no pasa nada, otro worker lo hizo
                logger.debug(f"Otro worker ya limpió la tabla o hubo conflicto: {e}")
                

async def worker_loop():
    logger.info("🚀 Worker iniciado y consumiendo tareas de Redis...")
    while True:
        path = await pop_task()
        if path:
            try:
                await process_folder_task(path)
            except Exception as e:
                logger.error(f"❌ Error crítico procesando {path}: {e}")
        else:
            # Si no hay tareas, espera un poco
            await asyncio.sleep(1)

async def main():
    # Siempre intentamos migrar pendientes primero (toma microsegundos si está vacía)
    await migrate_pending_to_redis()
    
    if MODE == "WORKER":
        await worker_loop()
    elif MODE == "PRODUCER":
        # Si configuras un contenedor como producer, aquí empezarías el escaneo raíz
        logger.info("Iniciando escaneo Producer desde raíz...")
        await push_task("/") # Inicia la cadena
    else:
        logger.error(f"Modo desconocido: {MODE}")

if __name__ == "__main__":
    asyncio.run(main())