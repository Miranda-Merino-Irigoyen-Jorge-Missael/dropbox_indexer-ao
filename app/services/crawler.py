# app/services/crawler.py
import logging
from datetime import datetime
from typing import Tuple, List
from pathlib import PurePosixPath
from urllib.parse import quote

from dropbox import Dropbox, exceptions, files
from dropbox.files import FileMetadata, FolderMetadata
from dropbox.common import PathRoot

from app.queue_local import push_task
from app.services.auth_service import auth_service
from app.services.pubsub_mgr import pubsub_mgr
from app.database import bulk_upsert

logger = logging.getLogger(__name__)


def get_parent_path(path: str) -> str:
    """Extract parent path from a given path."""
    if not path or path == "/":
        return ""
    parent = str(PurePosixPath(path).parent)
    return parent if parent != "." else ""


def generate_web_url(path_display: str) -> str:
    """
    Genera la URL web de Dropbox sin llamar a la API.
    """
    if not path_display:
        return ""
    encoded_path = quote(path_display)
    return f"https://www.dropbox.com/home{encoded_path}"


def configure_dropbox_client(dbx: Dropbox) -> Dropbox:
    """
    Detecta si la cuenta pertenece a un equipo y configura el Root Namespace.
    Esto permite ver carpetas compartidas y de equipo que de otra forma estarían ocultas.
    """
    try:
        # Consultamos la cuenta actual
        account = dbx.users_get_current_account()
        
        # Verificamos si tiene un Root Namespace (Team)
        if account.root_info and hasattr(account.root_info, 'root_namespace_id'):
            root_ns_id = account.root_info.root_namespace_id
            logger.info(f"🏢 Configurando Team Namespace: {root_ns_id}")
            
            # Devolvemos el cliente configurado para ver la raíz del equipo
            return dbx.with_path_root(PathRoot.namespace_id(root_ns_id))
            
    except Exception as e:
        logger.warning(f"⚠️ No se pudo configurar el Team Namespace (se usará vista personal): {e}")
    
    return dbx


def classify_entries(entries: list) -> Tuple[List[dict], List[dict]]:
    """
    Classify Dropbox entries into files and folders.
    """
    files = []
    folders = []

    for entry in entries:
        # Generamos la URL web
        web_url = generate_web_url(entry.path_display)

        base_item = {
            "id": entry.id,
            "name": entry.name,
            "path_display": entry.path_display,
            "path_lower": entry.path_lower,
            "parent_path_lower": get_parent_path(entry.path_lower),
            "web_url": web_url,  # Incluimos la URL
            "indexed_at": datetime.utcnow()
        }

        if isinstance(entry, FileMetadata):
            files.append({
                **base_item,
                "type": "file",
                "size": entry.size,
                "content_hash": getattr(entry, 'content_hash', None),
                "client_modified": entry.client_modified
            })
        elif isinstance(entry, FolderMetadata):
            folders.append({
                **base_item,
                "type": "folder",
                "size": 0,
                "content_hash": None,
                "client_modified": None
            })

    return files, folders


async def process_folder_task(path: str) -> dict:
    """
    Main worker logic: Process a single folder task.
    Ahora con lógica de reintento automático si el token expira (Error 401).
    """
    logger.info(f"Starting to process folder: {path}")

    all_entries = []
    
    # --- INICIO DEL BUCLE DE INTENTOS (RETRY LOGIC) ---
    # Intentamos máximo 2 veces. Si falla el token a la primera, pedimos uno nuevo.
    for attempt in range(1, 3):
        try:
            # 1. Obtener Token
            # Si es el intento > 1, forzamos la renovación del token (force_refresh=True)
            force_refresh = (attempt > 1)
            token = await auth_service.get_valid_token(force_refresh=force_refresh)
            
            # Inicializamos cliente
            dbx = Dropbox(token)
            
            # Configurar el Namespace de Equipo
            dbx = configure_dropbox_client(dbx)

            # 2. Listar contenido
            list_path = "" if path == "/" else path
            
            # Primera llamada a la API
            result = dbx.files_list_folder(list_path)
            all_entries.extend(result.entries)

            # Paginación (si hay muchos archivos)
            while result.has_more:
                result = dbx.files_list_folder_continue(result.cursor)
                all_entries.extend(result.entries)
                logger.debug(f"Fetched {len(all_entries)} entries so far for {path}")
            
            # ¡Si llegamos aquí, tuvimos éxito! Rompemos el bucle.
            break

        except exceptions.AuthError as e:
            # --- CAPTURA DE ERROR DE TOKEN ---
            if e.error.is_expired_access_token():
                logger.warning(f"⚠️ Token expirado detectado en intento {attempt} para {path}. Renovando...")
                # Al hacer 'continue', el bucle vuelve arriba e intenta de nuevo con force_refresh=True
                continue
            
            # Si es otro error de autenticación (ej. permiso denegado), lanzamos el error
            logger.error(f"Error de Autenticación fatal: {e}")
            raise e

        except exceptions.ApiError as e:
            # --- CAPTURA DE ERROR DE CARPETA NO ENCONTRADA ---
            if isinstance(e.error, files.ListFolderError) and \
               e.error.is_path() and \
               e.error.get_path().is_not_found():
                
                logger.warning(f"⚠️ La carpeta ya no existe (omitida): {path}")
                return {
                    "path": path,
                    "files_count": 0,
                    "folders_count": 0,
                    "tasks_published": 0,
                    "status": "skipped_not_found"
                }
            
            # Otros errores de API se lanzan para que Pub/Sub reintente
            logger.error(f"Error listing folder {path}: {e}")
            raise e

        except Exception as e:
            logger.error(f"Error inesperado en intento {attempt}: {e}")
            # Si es el último intento, dejamos que falle
            if attempt == 2:
                raise e
    # --- FIN DEL BUCLE ---

    # 3. Classify and prepare data (Esto no cambia)
    files_buffer, folders_buffer = classify_entries(all_entries)

    # 4. Bulk UPSERT to database (idempotent)
    all_items = files_buffer + folders_buffer
    if all_items:
        await bulk_upsert(all_items)

    # 5. Fan-out: Publish subfolder tasks to Pub/Sub
    published_count = 0
    for folder in folders_buffer:
        await push_task(folder["path_display"])
        published_count += 1

    stats = {
        "path": path,
        "files_count": len(files_buffer),
        "folders_count": len(folders_buffer),
        "tasks_published": published_count
    }

    logger.info(
        f"Processed {path}: "
        f"{stats['files_count']} files, "
        f"{stats['folders_count']} folders, "
        f"{stats['tasks_published']} new tasks published"
    )

    return stats