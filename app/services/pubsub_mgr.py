# app/services/pubsub_mgr.py
import json
import logging
from app.config import get_settings
from app.database import save_pending_request

logger = logging.getLogger(__name__)
settings = get_settings()

class PubSubManager:
    """Wrapper modificado para MIGRACIÓN: Guarda en SQL en lugar de Pub/Sub."""

    def __init__(self):
        # 🗑️ ELIMINAMOS las referencias a gcp_project_id y pubsub_topic_name
        # porque ya no existen en config.py ni las usamos aquí.
        pass

    async def publish_folder_task(self, path: str):
        """
        MODIFICADO PARA MIGRACIÓN:
        En lugar de Pub/Sub, guardamos en la tabla SQL 'pending_requests'.
        """
        try:
            # --- LÓGICA DE DESVÍO ---
            logger.info(f"🛑 Desviando tarea a tabla SQL pendiente: {path}")
            await save_pending_request(path)
            return "saved_to_db"

        except Exception as e:
            logger.error(f"Error guardando pending request {path}: {e}")
            # No lanzamos error para no detener el worker, pero el log queda registrado.
            return None

    async def publish_batch(self, paths: list[str]) -> list[str]:
        """
        Ahora es ASYNC. Guarda múltiples rutas en la tabla SQL.
        """
        message_ids = []
        for path in paths:
            # AQUI ESTABA EL ERROR: Faltaba el await
            msg_id = await self.publish_folder_task(path)
            if msg_id:
                message_ids.append(msg_id)

        logger.info(f"Guardadas {len(message_ids)} tareas en SQL (Desviadas)")
        return message_ids

pubsub_mgr = PubSubManager()