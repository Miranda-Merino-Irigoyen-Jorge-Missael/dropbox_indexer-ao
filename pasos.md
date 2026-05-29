# Pasos

### 1. La Nueva Arquitectura (Local)

En la nube usabas servicios gestionados (Pub/Sub, Cloud SQL). En local, usaremos contenedores Docker para simular esos servicios.

* **Google Pub/Sub  Redis:** Redis es ultrarrápido para colas locales. Usaremos una lista simple de Redis como tu "Topic".
* **Cloud SQL  PostgreSQL Docker:** Una base de datos Postgres corriendo en un contenedor al lado de tu app.
* **Workers  Replicas de Docker:** En lugar de "hilos", usaremos múltiples contenedores (procesos) orquestados por Docker Compose.

---

### 2. ¿Qué hacer con los 10 TB ya indexados?

**No los pierdas.** Tienes que hacer un "Dump & Restore".
Dado que vas a mover la base de datos a local para tener velocidad máxima (latencia 0ms), sigue estos pasos antes de apagar Cloud Run:

1. **Exportar (Desde Google Cloud):**
Usa `pg_dump` desde tu consola o desde una máquina con acceso:
```bash
pg_dump -h IP_CLOUD_SQL -U usuario -d dropbox_db -Fc > backup_10tb.dump

```


2. **Importar (En el servidor Local):**
Una vez que IT levante el contenedor de Postgres local:
```bash
pg_restore -h localhost -U usuario -d dropbox_db -v backup_10tb.dump

```



*Nota: Si prefieres, puedes dejar la DB en la nube y conectar el servidor local a Cloud SQL, pero perderás rendimiento por la latencia de internet.*

---

### 3. Hilos vs. Workers en Local

**Tu duda:** "¿Uso hilos o workers?"
**La respuesta:** Sigues usando tu código **Async** (que ya es eficiente internamente), pero escalarás usando **Procesos (Contenedores)**.

Como Python tiene el GIL (Global Interpreter Lock), un solo contenedor solo usa 1 núcleo de CPU al 100%. Si el servidor de IT tiene, digamos, **32 núcleos**, desplegaremos **20 o 25 réplicas** de tu contenedor. Docker Compose hace esto con una sola línea de configuración.

---

### 4. El Entregable para IT: `docker-compose.yml`

Este es el archivo mágico. Copia esto, guárdalo como `docker-compose.yml` y entrégaselo a IT junto con tu código. Esto levantará:

1. Tu Base de Datos.
2. Tu Cola de Mensajes (Redis).
3. Tu Crawler (Productor).
4. Tus Workers (Consumidores) x 20 copias.

```yaml
version: '3.8'

services:
  # 1. Base de Datos Local
  db:
    image: postgres:15-alpine
    restart: always
    environment:
      POSTGRES_USER: usuario
      POSTGRES_PASSWORD: password_secreto
      POSTGRES_DB: dropbox_indexer
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    # Tunning básico para alto rendimiento en local
    command: postgres -c 'max_connections=500' -c 'shared_buffers=1GB'

  # 2. Cola de Mensajes (Reemplazo de Pub/Sub)
  redis:
    image: redis:alpine
    restart: always
    ports:
      - "6379:6379"

  # 3. Tu Worker (El indexador)
  worker:
    build: .  # Construye la imagen desde tu carpeta actual
    restart: always
    depends_on:
      - db
      - redis
    deploy:
      mode: replicated
      replicas: 20  # <--- AQUÍ DEFINES EL PODER (Similar a max-instances)
    environment:
      - DATABASE_URL=postgresql+asyncpg://usuario:password_secreto@db:5432/dropbox_indexer
      - REDIS_URL=redis://redis:6379/0
      - MODE=WORKER
      - CONCURRENCY=50  # Mantenemos tu async interno
      - APP_DROPBOX_TOKEN=tu_token_aqui
    # Comando para iniciar escuchando Redis
    command: python -m app.main_local worker

  # 4. El Productor (El que escanea carpetas y llena la cola)
  producer:
    build: .
    restart: on-failure
    depends_on:
      - redis
    environment:
      - REDIS_URL=redis://redis:6379/0
      - MODE=PRODUCER
      - APP_DROPBOX_TOKEN=tu_token_aqui
    # Comando para iniciar escaneo
    command: python -m app.main_local producer

volumes:
  postgres_data:

```

---

### 5. Ajustes necesarios en tu Código (Python)

Necesitas crear un pequeño archivo adaptador (`app/queue_local.py`) para que tu código use Redis en lugar de Google Pub/Sub cuando corra en local.

**Ejemplo simple de adaptación:**

```python
# app/queue_local.py
import json
import redis.asyncio as redis
import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = "dropbox_tasks"

async def push_task(task_data: dict):
    """Reemplaza a publisher.publish()"""
    r = redis.from_url(REDIS_URL)
    await r.lpush(QUEUE_NAME, json.dumps(task_data))
    await r.aclose()

async def get_task():
    """Reemplaza la suscripción de Pub/Sub"""
    r = redis.from_url(REDIS_URL)
    # blpop espera hasta que haya algo en la lista (bloqueante eficiente)
    result = await r.blpop(QUEUE_NAME, timeout=5) 
    await r.aclose()
    if result:
        return json.loads(result[1])
    return None

```

Y crearías un `app/main_local.py` que use este adaptador:

* **Producer:** Hace un loop de carpetas y llama a `push_task`.
* **Worker:** Hace un `while True`, llama a `get_task()` y si hay tarea, ejecuta tu `process_folder_task`.

### Pasos para ti ahora:

1. **Dile a IT:** "Solo necesito que instalen **Docker** y **Docker Compose** en el servidor. Yo les paso el archivo de configuración y la imagen".
2. **Backup:** Haz el `pg_dump` de Cloud SQL hoy mismo para tener tus 10TB a salvo.
3. **Código:** ¿Quieres que te ayude a escribir el `main_local.py` para que funcione con Redis y puedas hacer la transición suave?