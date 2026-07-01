import os
import csv
import re
import io
import time
import logging
from datetime import datetime
from dotenv import load_dotenv
from dropbox.common import PathRoot

import gspread
import dropbox
from dropbox.exceptions import ApiError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError

# ==========================================
# CONFIGURACIÓN DE LOGS PROFESIONALES
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"migracion_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    ]
)
logger = logging.getLogger("Drive2Dropbox")

# ==========================================
# CONSTANTES Y VARIABLES DE ENTORNO
# ==========================================
load_dotenv()

# Google SCOPES requeridos: Hojas de cálculo (Lectura) y Drive (Lectura de archivos)
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly"
]

CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Copia de HISTORICO")
DROPBOX_TOKEN = os.getenv("DROPBOX_ACCESS_TOKEN")

# MIME Types exportables
MIME_PDF = "application/pdf"
DOC_MIME_TYPE = "application/vnd.google-apps.document"

def autenticar_google():
    """Autentica con Google y devuelve las credenciales."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds

def extraer_id_drive(url: str) -> str:
    """Extrae el ID del archivo de un link de Google Drive."""
    if not url:
        return None
    match = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    return match.group(1) if match else None

def descargar_archivo_drive(drive_service, file_id: str) -> tuple:
    """
    Descarga el archivo desde Drive. Si es un Google Doc nativo, lo exporta a PDF.
    Retorna (bytes_del_archivo, nombre_del_archivo).
    """
    try:
        # Obtener metadatos para saber el tipo de archivo y nombre
        file_meta = drive_service.files().get(fileId=file_id, fields="name, mimeType").execute()
        file_name = file_meta.get('name')
        mime_type = file_meta.get('mimeType')

        fh = io.BytesIO()

        if mime_type == DOC_MIME_TYPE:
            # Es un Google Doc, lo exportamos como PDF
            request = drive_service.files().export_media(fileId=file_id, mimeType=MIME_PDF)
            if not file_name.endswith('.pdf'):
                file_name += '.pdf'
        else:
            # Es un archivo binario normal (pdf, docx, etc.)
            request = drive_service.files().get_media(fileId=file_id)

        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        
        return fh.getvalue(), file_name

    except HttpError as error:
        if error.resp.status in [403, 401]:
            raise PermissionError("SIN PERMISOS DE ACCESO")
        elif error.resp.status == 404:
            raise FileNotFoundError("ARCHIVO NO ENCONTRADO")
        else:
            raise Exception(f"ERROR API GOOGLE: {error.resp.status}")

def subir_a_dropbox(dbx, file_bytes: bytes, destination_path: str):
    """Sube los bytes descargados a la ruta específica de Dropbox."""
    try:
        dbx.files_upload(file_bytes, destination_path, mode=dropbox.files.WriteMode("overwrite"))
    except ApiError as err:
        raise Exception(f"ERROR DROPBOX: {err}")

def configurar_namespace_equipo(dbx):
    """Fuerza a la API a mirar los archivos del Equipo (Team Space)"""
    try:
        account = dbx.users_get_current_account()
        if account.root_info and hasattr(account.root_info, 'root_namespace_id'):
            root_ns_id = account.root_info.root_namespace_id
            logger.info(f"Cambiando al Team Namespace: {root_ns_id}")
            return dbx.with_path_root(PathRoot.namespace_id(root_ns_id))
    except Exception as e:
        logger.warning(f"No se pudo configurar Team Namespace: {e}")
    return dbx


# Mapeo de los enlaces que proporcionaste
URLS_CARPETAS = {
    "2024": "https://www.dropbox.com/scl/fo/cslavux0dfmwxnjhu6yr0/AHcm9x-M5wKWbGhVTOEea2E?rlkey=tu415lmke3gih1bsdtptid6fc&st=iz2ypx1g&dl=0",
    "2025": "https://www.dropbox.com/scl/fo/tytosd9v2o517zhr2nuf0/ANMZ7lQtb9o8h0jJfpWnoWs?rlkey=5oi0b46gz3tru2u6a8t87unqm&st=7q8y7ug6&dl=0",
    "2026": "https://www.dropbox.com/scl/fo/22099c7elz0894mxcs0lg/AFTr935l8CKXSdG2-n7VwXg?rlkey=n6y02v4weusbdndh2gtyubaq2&st=ifqorp5t&dl=0"
}

def procesar_migracion():
    # 1. Configurar APIs
    logger.info("Autenticando servicios de Google...")
    google_creds = autenticar_google()
    
    gc = gspread.authorize(google_creds)
    drive_service = build('drive', 'v3', credentials=google_creds)
    
    logger.info("Conectando a Dropbox...")
    dbx = dropbox.Dropbox(DROPBOX_TOKEN)
    dbx = configurar_namespace_equipo(dbx)

    # =========================================================
    # NUEVO: RESOLVER RUTAS EXACTAS DESDE LOS LINKS COMPARTIDOS
    # =========================================================
    logger.info("Resolviendo rutas internas desde los links de Dropbox...")
    rutas_base = {}
    for anio, url in URLS_CARPETAS.items():
        try:
            # Le pedimos a Dropbox los metadatos del link para obtener su ruta interna
            link_meta = dbx.sharing_get_shared_link_metadata(url=url)
            rutas_base[anio] = link_meta.path_lower
            logger.info(f"Carpeta {anio} enlazada correctamente a la ruta interna: {link_meta.path_lower}")
        except Exception as e:
            logger.critical(f"No se pudo resolver el link del año {anio}. Error: {e}")
            return # Detenemos el script si no encontramos las carpetas base

    # 2. Leer Hoja de Cálculo
    logger.info(f"Abriendo Spreadsheet ID: {SHEET_ID} | Hoja: {SHEET_NAME}")
    sheet = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    datos = sheet.get_all_values()
    
    if not datos:
        logger.error("La hoja de cálculo está vacía.")
        return

    csv_filename = f"resultados_migracion_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    resultados = []

    logger.info(f"Se encontraron {len(datos)} filas. Comenzando procesamiento...")
    
    for i, fila in enumerate(datos[1:], start=2):
        if len(fila) < 28:
            continue
            
        cliente_id = fila[0].strip()
        drive_link = fila[8].strip()
        anio = fila[27].strip()
        
        if not cliente_id or not drive_link:
            continue
            
        if anio not in rutas_base:
            logger.warning(f"Fila {i} | Cliente: {cliente_id} - Año inválido '{anio}', saltando.")
            resultados.append({"CLIENTE_ID": cliente_id, "ESTADO": f"AÑO INVÁLIDO ({anio})"})
            continue

        file_id = extraer_id_drive(drive_link)
        if not file_id:
            logger.warning(f"Fila {i} | Cliente: {cliente_id} - URL inválida")
            resultados.append({"CLIENTE_ID": cliente_id, "ESTADO": "URL INVÁLIDA"})
            continue

        try:
            logger.info(f"Fila {i} | Descargando archivo para cliente {cliente_id}...")
            file_bytes, file_name = descargar_archivo_drive(drive_service, file_id)
            
            file_name = re.sub(r'[\\/*?:"<>|]', "", file_name)
            
            # Construir ruta de Dropbox usando la ruta que resolvimos al principio + el nombre del archivo
            dropbox_path = f"{rutas_base[anio]}/{cliente_id}_{file_name}"
            
            logger.info(f"Fila {i} | Subiendo a Dropbox -> {dropbox_path}")
            subir_a_dropbox(dbx, file_bytes, dropbox_path)
            
            resultados.append({"CLIENTE_ID": cliente_id, "ESTADO": "EXITO"})
            logger.info(f"Fila {i} completada con éxito.")

        except PermissionError as pe:
            logger.error(f"Fila {i} | Cliente: {cliente_id} - {str(pe)}")
            resultados.append({"CLIENTE_ID": cliente_id, "ESTADO": str(pe)})
        except FileNotFoundError as fnf:
            logger.error(f"Fila {i} | Cliente: {cliente_id} - {str(fnf)}")
            resultados.append({"CLIENTE_ID": cliente_id, "ESTADO": "ARCHIVO NO ENCONTRADO"})
        except Exception as e:
            logger.error(f"Fila {i} | Cliente: {cliente_id} - Error inesperado: {str(e)}")
            resultados.append({"CLIENTE_ID": cliente_id, "ESTADO": "ERROR DESCONOCIDO"})
        
        time.sleep(1)

    logger.info("Guardando CSV de reporte...")
    with open(csv_filename, mode='w', encoding='utf-8', newline='') as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["CLIENTE_ID", "ESTADO"])
        writer.writeheader()
        writer.writerows(resultados)
        
    logger.info(f"Migración completada. Reporte guardado en: {csv_filename}")

if __name__ == "__main__":
    procesar_migracion()