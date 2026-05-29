# Dropbox Metadata Indexer (DMI)

Indexador masivo y asíncrono de metadatos de Dropbox hacia PostgreSQL usando un patrón **fan‑out** con Pub/Sub y Cloud Run. Cada carpeta se procesa en un worker independiente, evitando cuellos de botella y permitiendo escalar a decenas de millones de objetos.

## Características
- Fan‑out recursivo: cada carpeta encontrada publica una nueva tarea en Pub/Sub.
- Idempotencia completa vía `UPSERT` y `UNIQUE(path_lower)` en PostgreSQL.
- Tokens gestionados por el microservicio **AccessTokenDropbox** (no se guardan credenciales locales).
- Soporte para espacios de equipo de Dropbox (Team Namespace) sin configuración adicional.
- Modo local con Redis como cola y PostgreSQL en Docker; modo cloud con Pub/Sub + Cloud Run.

## Requisitos
- Python 3.11+
- Docker y Docker Compose (para entorno local)
- Cuenta de GCP con Pub/Sub y Cloud SQL (PostgreSQL 15)
- Credenciales de servicio con permisos Pub/Sub Publisher y acceso a Cloud SQL

## Estructura del repositorio
```
dropbox-indexer/
├── app/
│   ├── main.py               # FastAPI que recibe pushes de Pub/Sub (Cloud Run)
│   ├── main_local.py         # Loop local basado en Redis
│   ├── queue_local.py        # Cola y deduplicación en Redis
│   ├── config.py             # Variables de entorno
│   ├── database.py           # Modelo + conexión async SQLAlchemy
│   └── services/
│       ├── auth_service.py   # Cliente del microservicio AccessTokenDropbox
│       ├── crawler.py        # Lógica principal: listar, upsert, fan‑out
│       └── pubsub_mgr.py     # Wrapper (cloud) para publicar tareas
├── scripts/seed_trigger.py   # Envia la tarea semilla a Pub/Sub
├── docker-compose.yaml       # Stack local: PostgreSQL + Redis + workers
├── Dockerfile                # Imagen para Cloud Run
└── requirements.txt
```

## Variables de entorno (principales)
```
TOKEN_SERVICE_URL=https://accesstokendropbox-223080314602.us-central1.run.app
API_SECRET_KEY=clave-secreta-para-auth-service
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dropbox_index
REDIS_URL=redis://redis:6379/0          # Solo entorno local
GCP_PROJECT_ID=nexus-legal-ops
PUBSUB_TOPIC_NAME=dropbox-crawl-tasks
LOG_LEVEL=INFO
```

## Cómo correr en local (Docker Compose)
1) Crear/ajustar un archivo `.env` en la raíz con las variables anteriores (la URL de DB ya apunta al servicio `db`).
2) Levantar la stack:
```bash
docker compose up --build
```
- `db` expone el puerto 5433 para inspección local.
- `worker` usa `MODE=WORKER` y consume tareas desde Redis.

3) Iniciar el escaneo sembrando la raíz en Redis:
```bash
docker compose exec worker python -m app.queue_local  # opcional para probar conexión
docker compose exec worker python -m app.main_local   # arranca loop si no está corriendo
```
Para disparar la primera tarea automáticamente, puedes iniciar un contenedor en modo `PRODUCER`:
```bash
MODE=PRODUCER docker compose run --rm worker python -m app.main_local
```

## Sembrar en Pub/Sub (entorno cloud)
Usa el script incluido (requiere `gcloud auth application-default login` o variable `GOOGLE_APPLICATION_CREDENTIALS`):
```bash
python scripts/seed_trigger.py --project-id "$GCP_PROJECT_ID" --topic "$PUBSUB_TOPIC_NAME" --path "/"
```

## Despliegue en Cloud Run (ejemplo rápido)
```bash
gcloud builds submit --tag gcr.io/$GCP_PROJECT_ID/dropbox-indexer

gcloud run deploy dropbox-indexer-worker \ 
  --image gcr.io/$GCP_PROJECT_ID/dropbox-indexer \ 
  --region us-central1 \ 
  --max-instances 5 \ 
  --set-env-vars "TOKEN_SERVICE_URL=$TOKEN_SERVICE_URL" \ 
  --set-secrets "API_SECRET_KEY=api-secret-key:latest,DATABASE_URL=db-url:latest"
```
Luego crea una suscripción *push* de Pub/Sub apuntando a la URL del servicio. Incrementa `--max-instances` según la capacidad de Dropbox API y Cloud SQL.

## Endpoints principales
- `GET /health` — estado del worker (usado por Cloud Run / load balancer)
- `POST /` — receptor de Pub/Sub (no se llama manualmente)
- `POST /manual?path=/Carpeta` — trigger manual para pruebas rápidas

## Flujos internos (resumen)
- Cada mensaje contiene `{ "path": "..." }` codificado en Base64.
- El worker obtiene token fresco del microservicio; si expira, reintenta automáticamente.
- Se listan entradas de Dropbox (paginadas), se clasifican y se hace `bulk_upsert` en bloques de 1000.
- Por cada carpeta hija se publica una nueva tarea (Pub/Sub o Redis).
- Deduplicación: `path_lower` es `UNIQUE` en DB; en local Redis usa un `SET` para evitar re-enqueue.

## Base de datos
Tabla principal: `dropbox_items`
- Clave primaria `id` de Dropbox; restricción `UNIQUE(path_lower)` para idempotencia.
- Índices: `idx_parent_path`, `idx_type`.
Tabla auxiliar: `pending_requests` (buffer temporal para migraciones a Redis en local).

## Desarrollo
- Instalar dependencias: `pip install -r requirements.txt`.
- Linter/formato no están definidos; sigue PEP8.
- Ejecutar app local sin Docker (requiere Redis y Postgres accesibles):
```bash
export DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/dropbox_index
export REDIS_URL=redis://localhost:6379/0
uvicorn app.main:app --reload --port 8080
```

## Solución de problemas rápida
- **Race conditions en inserción**: se registran como warning y se omite el lote; el modelo es eventual-consistente.
- **Token expirado (401)**: se renueva automáticamente en el siguiente intento.
- **Carpeta eliminada**: se marca `skipped_not_found` y el flujo continúa.

## Licencia
Uso interno. No distribuido públicamente.
