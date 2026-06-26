import csv
import asyncio
import logging
from sqlalchemy import select
from app.database import AsyncSessionLocal, DropboxItem, init_db
from app.config import get_settings

# Configurar logging básico para ver el progreso
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

async def search_clients_in_db(csv_filepath: str, output_filepath: str):
    # 1. Leer los clientes del CSV
    clientes = []
    try:
        with open(csv_filepath, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            # Como la 1ra fila es el encabezado 'CLIENTE', la saltamos
            next(reader, None) 
            for row in reader:
                if row: # ignorar filas vacías
                    # Asumiendo que el nombre del cliente está en la primera columna (índice 0)
                    nombre_cliente = row[0].strip().lower() 
                    if nombre_cliente:
                        clientes.append(nombre_cliente)
    except Exception as e:
        logger.error(f"Error al leer el archivo CSV: {e}")
        return

    logger.info(f"Se cargaron {len(clientes)} clientes del archivo CSV.")

    # 2. Conectarse a la BD y buscar cada cliente
    resultados = []
    
    async with AsyncSessionLocal() as session:
        for index, cliente in enumerate(clientes):
            if index % 100 == 0 and index > 0:
                 logger.info(f"Procesando... {index}/{len(clientes)}")

            # Ignorar palabras súper cortas que causan falsos positivos (menores a 3 letras)
            if len(cliente) < 3:
                resultados.append({
                    "cliente": cliente, 
                    "path": "Ignorado (muy corto)", 
                    "web_url": "Ignorado (muy corto)"
                })
                continue

            # Buscar si el nombre del cliente (en minúsculas) es parte de algun path_lower
            # Filtrado también para que SOLO traiga carpetas (type == 'folder')
            stmt = select(DropboxItem.web_url, DropboxItem.path_display).where(
                DropboxItem.path_lower.like(f"%{cliente}%"),
                DropboxItem.type == 'folder'
            ).limit(1) # Solo necesitamos saber si existe al menos 1

            result = await session.execute(stmt)
            row = result.first()

            if row:
                resultados.append({
                    "cliente": cliente, 
                    "path": row[1], 
                    "web_url": row[0] if row[0] else ""
                })
            else:
                resultados.append({
                    "cliente": cliente, 
                    "path": "No encontrado", 
                    "web_url": "No encontrado"
                })

    # 3. Guardar los resultados en un nuevo CSV
    try:
        with open(output_filepath, mode='w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=["cliente", "path", "web_url"])
            writer.writeheader()
            writer.writerows(resultados)
        logger.info(f"¡Proceso terminado! Resultados guardados en: {output_filepath}")
    except Exception as e:
         logger.error(f"Error al guardar el archivo de resultados: {e}")

async def main():
    # Asegurarnos de que el motor de bd esté listo
    logger.info("Verificando conexión...")
    
    input_csv = "Case Review Word By Word - BUSQUEDA EO.csv"
    output_csv = "Resultados_Busqueda_Clientes.csv"
    
    await search_clients_in_db(input_csv, output_csv)

if __name__ == "__main__":
    asyncio.run(main())
