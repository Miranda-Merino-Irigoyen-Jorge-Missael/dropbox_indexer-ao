import os
import re
import time
import gspread
import dropbox
from urllib.parse import unquote
from dotenv import load_dotenv

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from dropbox.common import PathRoot

# 1. Cargar variables de entorno
load_dotenv()
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME")
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE")

DROPBOX_APP_KEY = os.getenv("DROPBOX_APP_KEY")
DROPBOX_APP_SECRET = os.getenv("DROPBOX_APP_SECRET")
DROPBOX_REFRESH_TOKEN = os.getenv("DROPBOX_REFRESH_TOKEN")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def obtener_path_principal(url: str) -> str:
    """Decodifica la URL y extrae solo la ruta interna (path) de la carpeta principal."""
    if not url or "dropbox.com/home" not in url:
        return None
        
    url_decodificada = unquote(url)
    base_dropbox = "https://www.dropbox.com/home"
    path = url_decodificada.replace(base_dropbox, "")
    
    partes = path.strip().split('/')
    patron = re.compile(r"^(1[0-2]|[1-9])(\.|\s|[a-zA-Z]|$)")
    
    path_principal = path
    for i, parte in enumerate(partes):
        if patron.match(parte):
            path_principal = '/'.join(partes[:i])
            break
            
    return path_principal

def configurar_dropbox():
    """Inicializa el cliente de Dropbox forzando el uso de un token temporal (Access Token)."""
    print("🔌 Conectando a Dropbox con token manual...")
    
    # Toma el token directamente del .env
    token = os.getenv("DROPBOX_ACCESS_TOKEN")
    
    if not token or not token.startswith("sl."):
        print("⚠️ ADVERTENCIA: El token no parece ser un Access Token temporal válido (debería empezar con 'sl.').")
        
    dbx = dropbox.Dropbox(token)
    
    # Configuración de Team Root (imprescindible para ver carpetas empresariales)
    try:
        account = dbx.users_get_current_account()
        if account.root_info and hasattr(account.root_info, 'root_namespace_id'):
            root_ns_id = account.root_info.root_namespace_id
            dbx = dbx.with_path_root(PathRoot.namespace_id(root_ns_id))
            print("🏢 Team Namespace configurado.")
    except Exception as e:
        print(f"⚠️ No se detectó Team Namespace o hubo un error con la cuenta: {e}")
        
    return dbx

def obtener_link_compartido(dbx, path: str) -> str:
    # Limpiamos cualquier espacio o barra inclinada al final por si acaso
    path = path.strip().rstrip('/')
    
    try:
        # Primero busca si ya existe un link generado para no duplicar
        links = dbx.sharing_list_shared_links(path=path, direct_only=True).links
        if links:
            return links[0].url
            
        # Si no existe, lo crea
        nuevo_link = dbx.sharing_create_shared_link_with_settings(path)
        return nuevo_link.url
        
    except dropbox.exceptions.ApiError as e:
        # Aquí capturamos los errores específicos de Dropbox (carpetas no encontradas, permisos, etc.)
        mensaje_error = str(e.error)
        print(f"    [!] Error de Dropbox: {mensaje_error}")
        return f"Error API"
        
    except dropbox.exceptions.RateLimitError as e:
        # Aquí capturamos si Dropbox nos pide que vayamos más lento
        print(f"    [!] Dropbox nos pide pausar... esperando {e.retry_after} segundos")
        time.sleep(e.retry_after)
        return "Reintentar (Rate Limit)"
        
    except Exception as e:
        # Cualquier otro error en Python
        print(f"    [!] Error en Python: {e}")
        return f"Error interno"

def autenticar_google():
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

def main():
    # Conexión a las dos APIs
    dbx = configurar_dropbox()
    
    print("🔌 Conectando a Google Sheets...")
    creds = autenticar_google()
    cliente_gspread = gspread.authorize(creds)
    sheet = cliente_gspread.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    
    datos = sheet.get_all_values()
    print(f"✅ Conectado. Procesando {len(datos)} filas...\n")
    print("-" * 50)
    
    celdas_a_actualizar = []
    
    # Procesar filas (empezando desde la fila 2 para saltar encabezados)
    for i, fila in enumerate(datos[1:], start=2):
        if len(fila) >= 3:
            cliente = fila[0]
            link_original = fila[2] # Columna C
            
            if link_original and "dropbox.com/home" in link_original:
                # 1. Obtener el path limpio
                path_principal = obtener_path_principal(link_original)
                
                # 2. Ir a Dropbox a pedir el link scl/fo/
                link_dropbox = obtener_link_compartido(dbx, path_principal)
                
                print(f"Fila {i} | {cliente}")
                print(f"  Path  : {path_principal}")
                print(f"  Link D: {link_dropbox}\n")
                
                # 3. Preparar la celda para escribir en la Columna D (Columna 4)
                celda = gspread.Cell(row=i, col=4, value=link_dropbox)
                celdas_a_actualizar.append(celda)
                
                # Pequeña pausa para no saturar la API de Dropbox
                time.sleep(0.3)
    
    # Actualizar Google Sheets en un solo movimiento (bulk update)
    if celdas_a_actualizar:
        print(f"💾 Guardando {len(celdas_a_actualizar)} enlaces en Google Sheets (Columna D)...")
        sheet.update_cells(celdas_a_actualizar)
        print("✅ ¡Actualización completada!")
    else:
        print("No se encontraron links válidos para procesar.")

if __name__ == "__main__":
    main()