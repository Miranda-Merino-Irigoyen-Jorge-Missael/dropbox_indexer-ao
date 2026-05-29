import logging
import sys
import requests
import dropbox
from dropbox import Dropbox
from dropbox.files import FileMetadata, FolderMetadata
from dropbox.common import PathRoot

# --- CONFIGURACIÓN ---
TEST_PATH = "/Open Cases" 
TOKEN_SERVICE_URL = "https://accesstokendropbox-223080314602.us-central1.run.app/api/v1/token"
API_SECRET_KEY = "930xY0dJ0pD"

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("tester")

def get_token():
    print(f"🔑 Solicitando token a {TOKEN_SERVICE_URL}...")
    try:
        response = requests.post(
            TOKEN_SERVICE_URL,
            json={"signature": API_SECRET_KEY, "service": "debug_script"},
            timeout=10
        )
        response.raise_for_status()
        return response.json().get("access_token")
    except Exception as e:
        print(f"❌ Error obteniendo token: {e}")
        sys.exit(1)

def configure_team_root(dbx: Dropbox):
    """
    Detecta si el usuario es de un equipo y configura el Root Namespace.
    Esto es VITAL para ver archivos compartidos de empresa.
    """
    try:
        account = dbx.users_get_current_account()
        
        # ¿Es una cuenta de equipo?
        if account.root_info and hasattr(account.root_info, 'root_namespace_id'):
            root_ns_id = account.root_info.root_namespace_id
            print(f"🏢 Detectada cuenta de Equipo.")
            print(f"   Cambio de vista al Namespace: {root_ns_id}")
            
            # Aquí ocurre la magia: Cambiamos la "lente" de la API
            return dbx.with_path_root(PathRoot.namespace_id(root_ns_id))
        else:
            print("👤 Cuenta Personal detectada (sin Root Namespace).")
            return dbx
            
    except Exception as e:
        print(f"⚠️ No se pudo configurar Team Root: {e}")
        return dbx

def test_dropbox_pagination(path):
    token = get_token()
    dbx = Dropbox(token)
    
    # 1. APLICAR CORRECCIÓN DE NAMESPACE
    dbx = configure_team_root(dbx)
    
    print(f"✅ Conexión establecida.")
    print(f"📂 ESCANEANDO RUTA: '{path}'")
    print("=" * 60)

    all_entries = []
    
    try:
        # Usamos recursive=False para ver solo el primer nivel
        # limit=100 para no saturar la pantalla
        result = dbx.files_list_folder(path, limit=100)
        
        all_entries.extend(result.entries)
        
        # Solo paginamos un par de veces para la prueba
        pages = 0
        while result.has_more and pages < 3:
            print(f"   --- Obteniendo más páginas... ---")
            result = dbx.files_list_folder_continue(result.cursor)
            all_entries.extend(result.entries)
            pages += 1
            
    except dropbox.exceptions.ApiError as e:
        print(f"❌ Error de API: {e}")
        if isinstance(e.error, dropbox.files.ListFolderError) and e.error.is_path():
             print(f"   El error indica que la ruta '{path}' no existe en este Namespace.")
        return

    # --- RESULTADOS ---
    files = [e for e in all_entries if isinstance(e, FileMetadata)]
    folders = [e for e in all_entries if isinstance(e, FolderMetadata)]

    print("=" * 60)
    print(f"📊 RESUMEN FINAL PARA: {path}")
    print(f"   Total encontrados: {len(all_entries)}")
    print(f"   📄 Archivos:       {len(files)}")
    print(f"   📁 Carpetas:       {len(folders)}")
    print("-" * 60)
    
    print("🔍 ARCHIVOS ENCONTRADOS:")
    if not files:
        print("   (Ninguno)")
    for f in files[:20]: # Mostrar los primeros 20
        print(f"   📄 {f.name}")

if __name__ == "__main__":
    path_to_test = sys.argv[1] if len(sys.argv) > 1 else TEST_PATH
    test_dropbox_pagination(path_to_test)