#!/usr/bin/env python3
"""
Script de inicialización de base de datos para el Indexador de Dropbox.

Ejecuta:
1. Habilita extensión pg_trgm (para búsqueda rápida de archivos)
2. Creación de tablas (Base.metadata.create_all)
3. Crea índices GIN en 'name' y 'path_lower' para búsqueda fuzzy

Uso:
    python scripts/init_db.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from app.config import get_settings
from app.database import Base 

def init_database():
    """Inicializa la base de datos con tablas e índices para Dropbox"""
    settings = get_settings()

    print("🗄️  Inicializando base de datos de Dropbox...")
    # Ocultamos la contraseña en la impresión por seguridad
    safe_url = settings.database_url.replace(settings.database_url.split('@')[0].split(':')[2], '****') if '@' in settings.database_url else settings.database_url
    print(f"📍 Database: {safe_url}")
    print()

    # Crear engine
    engine = create_engine(settings.database_url)

    # 1. Crear extensión pg_trgm (esencial para buscar nombres de archivos incompletos)
    print("[1/3] Habilitando extensión pg_trgm...")
    with engine.connect() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
            conn.commit()
            print("✅ Extensión pg_trgm habilitada")
        except Exception as e:
            print(f"⚠️  Error habilitando pg_trgm: {e}")
            print("    (Puede que ya esté habilitada o que el usuario no tenga permisos de superusuario)")

    # 2. Crear todas las tablas
    print("\n[2/3] Creando tablas...")
    try:
        Base.metadata.create_all(bind=engine)
        print("✅ Tablas creadas exitosamente")
    except Exception as e:
        print(f"❌ Error creando tablas: {e}")
        sys.exit(1)

    # 3. Crear índices GIN para búsqueda de archivos
    print("\n[3/3] Creando índices GIN para búsqueda de rutas y nombres...")
    with engine.connect() as conn:
        try:
            # Índice para el nombre del archivo
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_dropbox_name_gin
                ON dropbox_items
                USING gin (name gin_trgm_ops);
            """))
            
            # Índice para la ruta completa (path_lower)
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_dropbox_path_gin
                ON dropbox_items
                USING gin (path_lower gin_trgm_ops);
            """))
            conn.commit()
            print("✅ Índices GIN creados exitosamente")

        except Exception as e:
            print(f"❌ Error creando índices GIN: {e}")
            print("    La búsqueda de texto podría ser más lenta sin estos índices")

    print("\n🎉 ¡Base de datos de Dropbox inicializada correctamente!")


if __name__ == "__main__":
    init_database()