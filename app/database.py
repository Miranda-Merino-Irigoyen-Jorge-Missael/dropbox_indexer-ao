import logging
from datetime import datetime
from typing import List

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import (
    Column,
    String,
    BigInteger,
    Text,
    DateTime,
    Index
)
from sqlalchemy.dialects.postgresql import insert
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# 1. Configuración del motor Async
engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_size=10,       # Antes era 5. Ahora mantenemos 10 vivas.
    max_overflow=10,    # Antes era 5. Ahora permitimos picos de hasta 20 conexiones.
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True
)
# 2. Configuración de la sesión
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

Base = declarative_base()

class DropboxItem(Base):
    """Model for Dropbox file/folder metadata."""
    __tablename__ = "dropbox_items"

    id = Column(String(255), primary_key=True)
    name = Column(String(512), nullable=False)
    path_display = Column(Text, nullable=False)
    path_lower = Column(Text, nullable=False, unique=True) # Mantenemos unique, aunque upsert use ID
    type = Column(String(20), nullable=False)
    parent_path_lower = Column(Text, nullable=True)
    size = Column(BigInteger, default=0)
    content_hash = Column(String(128), nullable=True)
    client_modified = Column(DateTime, nullable=True)
    indexed_at = Column(DateTime, default=datetime.utcnow)
    web_url = Column(Text, nullable=True)
    
    __table_args__ = (
        Index('idx_parent_path', 'parent_path_lower'),
        Index('idx_type', 'type'),
    )

class PendingRequest(Base):
    """Tabla temporal para guardar tareas durante la migración."""
    __tablename__ = "pending_requests"

    path = Column(Text, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)

async def init_db():
    """Create all tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized")

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def bulk_upsert(items: List[dict]):
    """
    Inserta/Actualiza items. Si hay error de duplicados (Race Condition),
    lo ignora para no detener el worker, asumiendo que el otro worker ganó.
    """
    if not items:
        return

    BATCH_SIZE = 1000 
    total_items = len(items)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            for i in range(0, total_items, BATCH_SIZE):
                chunk = items[i : i + BATCH_SIZE]
                
                stmt = insert(DropboxItem).values(chunk)

                update_dict = {
                    'name': stmt.excluded.name,
                    'path_display': stmt.excluded.path_display,
                    'path_lower': stmt.excluded.path_lower,
                    'type': stmt.excluded.type,
                    'parent_path_lower': stmt.excluded.parent_path_lower,
                    'size': stmt.excluded.size,
                    'content_hash': stmt.excluded.content_hash,
                    'client_modified': stmt.excluded.client_modified,
                    'indexed_at': datetime.utcnow(),
                    'web_url': stmt.excluded.web_url 
                }

                upsert_stmt = stmt.on_conflict_do_update(
                    index_elements=['id'],
                    set_=update_dict
                )

                try:
                    await session.execute(upsert_stmt)
                except IntegrityError as e:
                    # Si falla por "path_lower_key", significa que otro worker insertó esta ruta
                    # con un ID diferente al mismo tiempo.
                    logger.warning(f"⚠️ Race condition detectada en lote {i}. Saltando lote para evitar crash. Error: {e.orig}")
                    # Opcional: Podrías intentar insertar 1 por 1 aquí si es crítico, 
                    # pero para un crawler masivo, saltar el error es más sano.
                    continue
                except Exception as e:
                    logger.error(f"❌ Error inesperado en DB: {e}")
                    raise e

async def save_pending_request(path: str):
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Usamos on_conflict_do_nothing para evitar errores si ya existe
            stmt = insert(PendingRequest).values(path=path).on_conflict_do_nothing()
            await session.execute(stmt)
