import asyncio
import logging
import sys
import os

# Aseguramos que pueda importar los módulos de 'app'
sys.path.append(os.getcwd())

from dropbox import Dropbox, files
from app.services.auth_service import auth_service
from app.services.crawler import configure_dropbox_client

# Configuración básica de logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DebugExplorer")

async def inspect_path(path: str):
    print(f"\n🔍 INSPECCIONANDO RUTA: '{path}'")
    print("-" * 50)

    try:
        # 1. Obtener Token Real
        print("1. Obteniendo token...")
        token = await auth_service.get_valid_token()
        
        # 2. Configurar Cliente con Team Namespace (Igual que en Producción)
        print("2. Configurando Team Namespace...")
        dbx = Dropbox(token)
        dbx = configure_dropbox_client(dbx)

        # 3. Listar la carpeta
        print(f"3. Llamando a API de Dropbox para: {path} ...")
        
        # Ajuste para listar la raíz si el path es "/"
        list_path = "" if path == "/" else path
        
        result = dbx.files_list_folder(list_path)
        
        # 4. Mostrar Resultados
        entries = result.entries
        print(f"\n✅ ÉXITO: Se encontraron {len(entries)} elementos en el primer nivel.\n")
        
        folders = [e for e in entries if isinstance(e, files.FolderMetadata)]
        files_list = [e for e in entries if isinstance(e, files.FileMetadata)]

        print(f"📁 CARPETAS ({len(folders)}):")
        for f in folders[:10]: # Muestra solo las primeras 10
            print(f"   - {f.path_display}")
        if len(folders) > 10: print("   ... y más")

        print(f"\n📄 ARCHIVOS ({len(files_list)}):")
        for f in files_list[:10]:
            print(f"   - {f.name} ({f.size / 1024 / 1024:.2f} MB)")
            
    except Exception as e:
        print(f"\n❌ ERROR FATAL: {e}")
        print("\nCONSEJO: Verifica mayúsculas, minúsculas y espacios.")
        print("Prueba listar la carpeta padre para ver el nombre real.")

if __name__ == "__main__":
    # Usa argumentos de línea de comandos o un valor por defecto
    target_path = sys.argv[1] if len(sys.argv) > 1 else "/"
    
    # Ejecutar loop asíncrono
    asyncio.run(inspect_path(target_path))