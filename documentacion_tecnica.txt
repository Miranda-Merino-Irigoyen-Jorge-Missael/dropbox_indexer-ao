# 📂 Dropbox Metadata Indexer (DMI)

**Versión:** 1.0.0
**Estado:** Diseño de Arquitectura
**Propósito:** Indexación masiva, asíncrona y escalable de metadatos de Dropbox (30TB+) hacia Cloud SQL, utilizando arquitectura Serverless (Fan-out Pattern).

---

## 1. Visión General de la Arquitectura

A diferencia de un script lineal, este sistema utiliza un patrón de **"Fan-out / Worker Pattern"** horizontal. No intentamos recorrer todo el árbol de una sola vez con un solo script, ya que eso causaría bloqueos de memoria y cuello de botella en la red. En su lugar, dividimos el trabajo: procesar una carpeta genera "tareas" independientes para procesar sus subcarpetas.

### Integración con AccessTokenDropbox

Este sistema no gestiona sus propios tokens. Para garantizar la seguridad y evitar la expiración de sesiones en ejecuciones largas, el DMI se integra con el microservicio interno **AccessTokenDropbox**. Cada Worker solicita un token válido (Bear token) al iniciar su tarea.

### Flujo de Datos

1. **Trigger Inicial:** Un script "semilla" envía la ruta raíz (`/`) a la cola de mensajes (Pub/Sub).
2. **El Worker (Cloud Run):**
* Recibe el mensaje: "Escanear `/Carpeta_A`".
* **Autenticación:** Llama a `AccessTokenDropbox` para obtener un token de Dropbox fresco.
* **Escaneo:** Consulta la API de Dropbox (`files/list_folder`) para esa ruta específica.
* **Persistencia (Archivos):** Guarda sus metadatos directamente en Cloud SQL usando operaciones idempotentes (`UPSERT`).
* **Recursividad (Carpetas):** Por cada subcarpeta encontrada, publica un *nuevo mensaje* en Pub/Sub ("Escanear `/Carpeta_A/Sub_1`").
* **Confirmación (ACK):** Notifica a Pub/Sub que la tarea finalizó con éxito.


3. **Escalado (Magia Serverless):** Cloud Run detecta el volumen de mensajes en Pub/Sub y levanta múltiples instancias (Workers) automáticamente para procesar el árbol en paralelo.

---

## 2. Stack Tecnológico

| Componente | Tecnología | Función |
| --- | --- | --- |
| **Lenguaje** | Python 3.11+ | Lógica del worker y scripts. |
| **Compute** | Google Cloud Run (Jobs/Service) | Ejecución de los workers (Un worker por carpeta). |
| **Mensajería** | Google Cloud Pub/Sub | Cola de tareas para manejar la recursividad. |
| **Base de Datos** | Cloud SQL (PostgreSQL 15) | Almacenamiento relacional de metadatos. |
| **Auth** | **AccessTokenDropbox** | Microservicio interno para gestión de tokens. |
| **API Cliente** | Dropbox Python SDK | Conexión con Dropbox API V2. |

---

## 3. Diseño de Base de Datos (Idempotencia)

Dado el volumen (estimado 20M+ registros), la estructura está optimizada para escritura. Usamos el concepto de **Idempotencia**: si el sistema falla a la mitad y reintenta, no debe haber duplicados.

### Tabla: `dropbox_items`

```sql
CREATE TABLE dropbox_items (
    id VARCHAR(255) PRIMARY KEY,        -- ID único de Dropbox (id:xxxx...)
    name VARCHAR(512) NOT NULL,         -- Nombre del archivo/carpeta
    path_display TEXT NOT NULL,         -- Ruta completa legible (/Caso/Doc.pdf)
    path_lower TEXT NOT NULL,           -- Ruta normalizada para búsquedas
    type VARCHAR(20) NOT NULL,          -- 'file' o 'folder'
    parent_path_lower TEXT,             -- Ruta del padre (para reconstruir árbol)
    size BIGINT DEFAULT 0,              -- Tamaño en bytes (0 para carpetas)
    content_hash VARCHAR(128),          -- Hash de Dropbox (para detectar cambios)
    client_modified TIMESTAMP,          -- Fecha de modificación
    indexed_at TIMESTAMP DEFAULT NOW(), -- Cuándo lo registramos
    
    -- Restricción crítica para el UPSERT (Idempotencia)
    CONSTRAINT uq_path_lower UNIQUE (path_lower)
);

-- Índices B-Tree para búsquedas rápidas en el backend
CREATE INDEX idx_parent_path ON dropbox_items(parent_path_lower);
CREATE INDEX idx_type ON dropbox_items(type);

```

---

## 4. Estructura del Proyecto

Repositorio: `dropbox-indexer`

```text
dropbox-indexer/
├── app/
│   ├── main.py              # Entrypoint (escucha HTTP desde Eventarc/PubSub)
│   ├── config.py            # Variables de entorno
│   ├── database.py          # Conexión a Cloud SQL con SQLAlchemy
│   └── services/
│       ├── auth_service.py  # Cliente para AccessTokenDropbox API
│       ├── crawler.py       # Lógica: Listar -> UPSERT -> Publicar a Pub/Sub
│       └── pubsub_mgr.py    # Wrapper para publicar nuevos mensajes
├── scripts/
│   └── seed_trigger.py      # Script para iniciar el proceso (envía "/")
├── Dockerfile
└── requirements.txt

```

---

## 5. Lógica del Worker (Pseudocódigo Detallado)

El archivo `app/services/crawler.py` es el corazón del sistema, ejecutado de forma distribuida.

```python
def process_folder_task(path: str):
    """
    1. Obtiene Token Fresco del microservicio.
    2. Obtiene listado de Dropbox para 'path'.
    3. Bulk UPSERT de Archivos y Carpetas en DB.
    4. Envía Carpetas a Pub/Sub.
    5. Confirma mensaje (ACK).
    """
    
    # 1. Autenticación Centralizada
    token = auth_service.get_valid_token()
    dbx = Dropbox(token)
    
    # 2. Obtener datos de Dropbox (con paginación)
    entries = dbx.files_list_folder(path)
    files_buffer, folders_buffer = classify_entries(entries)
            
    # 3. Guardar en DB (UPSERT: Insertar o Actualizar si ya existe)
    # Protege contra fallos de red o reintentos
    db.bulk_upsert(files_buffer + folders_buffer)
    
    # 4. Propagar recursividad (Fan-out)
    # Las subcarpetas se vuelven tareas independientes para otros Workers
    for folder in folders_buffer:
        pubsub.publish_message(topic_id, {"path": folder.path_display})
        
    log.info(f"Procesado {path}: {len(files_buffer)} archivos. {len(folders_buffer)} workers invocados.")
    # El retorno exitoso 200 OK envía el ACK a Pub/Sub automáticamente en Cloud Run.

```

---

## 6. Variables de Entorno Requeridas

Nota: **Ya no se necesitan credenciales de Dropbox aquí**, se delega al microservicio.

```ini
# Configuración Microservicio de Autenticación
TOKEN_SERVICE_URL=https://accesstokendropbox-223080314602.us-central1.run.app
API_SECRET_KEY=tu-clave-secreta-para-auth-service

# Configuración GCP
GCP_PROJECT_ID=nexus-legal-ops
PUBSUB_TOPIC_NAME=dropbox-crawl-tasks
GCP_REGION=us-central1

# Base de Datos
DATABASE_URL=postgresql://user:pass@host:5432/dropbox_index

```

---

## 7. Estrategia de Costos y Concurrencia (Workers vs Hilos)

Para mapear 30 TB no usamos Hilos (Threads) dentro de un servidor, usamos **Workers (Instancias)**: Un worker por carpeta.

1. **Control de Concurrencia (Cloud Run):**
* Configuraremos `max-instances` en Cloud Run.
* *Recomendación Inicial:* Empezar con **máximo 5 instancias**. Si el microservicio de tokens y la API de Dropbox responden bien, podemos subir a 20 o 50 para acelerar.
* *Ventaja:* No hay "Memory Error". Cada worker solo procesa una carpeta a la vez.


2. **Base de Datos:**
* Carga inicial (Heavy Load): Usar instancia estándar (ej. 4GB RAM).
* Mantenimiento (Light Load): Reducir a instancia Micro.


3. **Pub/Sub:**
* Costo prácticamente cero (mensajes de texto plano con la ruta).



---

## 8. Guía de Despliegue Rápido

### Paso 1: Infraestructura (GCP CLI)

```bash
# Crear Topic y Suscripción (Push para Cloud Run)
gcloud pubsub topics create dropbox-crawl-tasks
# (Se configura la suscripción PUSH apuntando a la URL del Cloud Run una vez desplegado)

# Crear Base de Datos
gcloud sql instances create dropbox-index-db --tier=db-custom-1-3840 ...

```

### Paso 2: Deploy del Worker

```bash
gcloud builds submit --tag gcr.io/PROJECT_ID/dropbox-indexer

# Desplegar en Cloud Run (Worker mode, escucha HTTP POST de Pub/Sub)
gcloud run deploy dropbox-indexer-worker \
  --image gcr.io/PROJECT_ID/dropbox-indexer \
  --max-instances 5 \
  --set-env-vars "TOKEN_SERVICE_URL=https://accesstokendropbox-223080314602.us-central1.run.app" \
  --set-secrets "API_SECRET_KEY=api-secret-key:latest,DATABASE_URL=db-url:latest"

```

### Paso 3: Iniciar (Semilla)

Ejecutar localmente o en Cloud Shell:

```bash
python scripts/seed_trigger.py --path "/"

```

*Esto inyecta el primer mensaje. El worker inicial despertará, leerá la raíz, llamará a AccessTokenDropbox por su token, y disparará las tareas subsecuentes.*