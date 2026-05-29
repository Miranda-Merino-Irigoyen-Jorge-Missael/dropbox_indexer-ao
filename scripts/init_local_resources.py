import os
from google.cloud import pubsub_v1
from google.api_core.exceptions import AlreadyExists

# Configuración
PROJECT_ID = "nexus-legal-ops"
TOPIC_ID = "dropbox-crawl-tasks"
SUBSCRIPTION_ID = "dropbox-crawl-sub"

# IMPORTANTE: Esta es la dirección de TU máquina vista desde DOCKER.
# En Linux, la IP del host desde Docker suele ser 172.17.0.1.
# El endpoint "/" es donde tu Worker espera recibir los mensajes POST.
PUSH_ENDPOINT = "http://172.17.0.1:8080/" 

publisher = pubsub_v1.PublisherClient()
subscriber = pubsub_v1.SubscriberClient()

topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)

def initialize():
    print(f"🔌 Conectando al emulador en {os.environ.get('PUBSUB_EMULATOR_HOST')}...")

    # 1. Crear Topic
    try:
        publisher.create_topic(request={"name": topic_path})
        print(f"✅ Topic creado: {topic_path}")
    except AlreadyExists:
        print(f"⚠️ El topic ya existe.")

    # 2. Crear Suscripción PUSH
    # Esto conecta el Emulador -> Tu Uvicorn
    push_config = pubsub_v1.types.PushConfig(push_endpoint=PUSH_ENDPOINT)

    try:
        subscriber.create_subscription(
            request={
                "name": subscription_path,
                "topic": topic_path,
                "push_config": push_config,
                "ack_deadline_seconds": 600
            }
        )
        print(f"✅ Suscripción PUSH creada (Timeout: 1200s) apuntando a: {PUSH_ENDPOINT}")
    except AlreadyExists:
        print("⚠️ La suscripción ya existe.")
        print("   NOTA: Si necesitas cambiar el timeout, borra el contenedor de Pub/Sub y reinicia.")

if __name__ == "__main__":
    if not os.environ.get("PUBSUB_EMULATOR_HOST"):
        print("❌ Error: Falta la variable PUBSUB_EMULATOR_HOST")
    else:
        initialize()