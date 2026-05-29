import asyncio
import logging
import sys
import os

# Aseguramos que pueda encontrar los módulos
sys.path.append(os.getcwd())

from dropbox import Dropbox, files
from dropbox.common import PathRoot
from app.services.auth_service import auth_service

# Configuración básica de logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CleanExplorer")

def configure_local_client(dbx: Dropbox) -> Dropbox:
    """
    Versión local de la configuración de Team Namespace
    para no depender de 'app.services.crawler'.
    """
    try:
        account = dbx.users_get_current_account()
        
        if account.root_info and hasattr(account.root_info, 'root_namespace_id'):
            root_ns_id = account.root_info.root_namespace_id
            print(f"🏢 Namespace de Equipo detectado: {root_ns_id}")
            return dbx.with_path_root(PathRoot.namespace_id(root_ns_id))
        else:
            print("👤 Cuenta personal (sin Team Root)")
            
    except Exception as e:
        print(f"⚠️ Aviso: No se pudo configurar el Team Namespace: {e}")
    
    return dbx

async def inspect_path(path: str):
    print(f"\n🔍 INSPECCIONANDO: '{path}'")
    print("-" * 50)

    try:
        # 1. Obtener Token (Usa tu servicio de auth que ya funciona)
        token = await auth_service.get_valid_token()
        
        # 2. Configurar Cliente
        dbx = Dropbox(token)
        dbx = configure_local_client(dbx)

        # 3. Listar
        # Ajuste: Si el path es "/", la API pide cadena vacía ""
        target = "" if path == "/" else path
        
        print(f"📡 Consultando API de Dropbox...")
        result = dbx.files_list_folder(target)
        
        entries = result.entries
        print(f"\n✅ RESULTADOS ENCONTRADOS: {len(entries)}")
        print("-" * 50)
        
        # Separar carpetas y archivos para visualizar mejor
        folders = [e for e in entries if isinstance(e, files.FolderMetadata)]
        file_items = [e for e in entries if isinstance(e, files.FileMetadata)]

        if folders:
            print(f"📂 CARPETAS ({len(folders)}):")
            for f in folders: 
                # Imprimimos el nombre exacto para que puedas copiar y pegar
                print(f"   '{f.path_display}'")
        
        if file_items:
            print(f"\n📄 ARCHIVOS ({len(file_items)}):")
            # Mostramos los primeros 5 archivos de ejemplo
            for f in file_items[:5]:
                size_mb = f.size / 1024 / 1024
                print(f"   - {f.name} ({size_mb:.2f} MB)")
            if len(file_items) > 5:
                print(f"   ... y {len(file_items)-5} más.")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        # Si es un error de path, Dropbox suele ser específico
        if "not_found" in str(e):
            print("👉 PISTA: La ruta no existe. Verifica mayúsculas/minúsculas o espacios.")

if __name__ == "__main__":
    # Toma el argumento de la terminal o usa "/" por defecto
    target_path = sys.argv[1] if len(sys.argv) > 1 else "/"
    asyncio.run(inspect_path(target_path))