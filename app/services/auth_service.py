# app/services/auth_service.py
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional

import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

class AuthService:
    """Client for AccessTokenDropbox microservice on Cloud Run."""

    def __init__(self):
        self.token_service_url = settings.token_service_url.rstrip('/')
        self.api_secret_key = settings.api_secret_key
        
        # Variables para el manejo de caché
        self._cached_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    async def get_valid_token(self, force_refresh: bool = False) -> str:
        """
        Obtiene un token de acceso.
        Args:
            force_refresh: Si es True, ignora el caché y pide uno nuevo.
        """
        # 1. Verificar caché (solo si no forzamos refresco)
        if not force_refresh and self._cached_token and self._token_expires_at:
            if datetime.utcnow() < self._token_expires_at:
                # Token válido en memoria
                return self._cached_token
            else:
                logger.info("Token en caché expirado. Solicitando nuevo...")

        # 2. Pedir nuevo token al microservicio
        return await self._fetch_new_token()

    async def _fetch_new_token(self) -> str:
        """Lógica interna para llamar al microservicio."""
        headers = {"Content-Type": "application/json"}
        payload = {
            "signature": self.api_secret_key, 
            "service": "dropbox-index"
        }
        endpoint = f"{self.token_service_url}/api/v1/token"

        async with httpx.AsyncClient(timeout=30.0) as client:
            logger.info(f"Obteniendo nuevo token de: {endpoint}")
            
            token = None
            last_error = None

            for attempt in range(1, 4):
                try:
                    response = await client.post(endpoint, json=payload, headers=headers)
                    response.raise_for_status()
                    
                    data = response.json()
                    token = data.get("access_token")
                    
                    if token:
                        break 
                except httpx.HTTPError as e:
                    last_error = e
                    logger.warning(f"Intento {attempt}/3 falló: {e}")
                    if attempt < 3:
                        await asyncio.sleep(1)

            if not token:
                logger.critical("No se pudo obtener el token después de 3 intentos.")
                raise ValueError(f"Falla de Auth: {last_error}")

            # 3. Guardamos en caché (Reducido a 55 minutos para seguridad)
            self._cached_token = token
            self._token_expires_at = datetime.utcnow() + timedelta(minutes=55)
            
            logger.info("✅ Nuevo Token obtenido y guardado (expira en 55 min)")
            return token

    def invalidate_cache(self):
        """Borra el token actual para forzar una renovación en la siguiente llamada."""
        logger.warning("Invalidando token en caché por error de autenticación.")
        self._cached_token = None
        self._token_expires_at = None

# Instancia global
auth_service = AuthService()