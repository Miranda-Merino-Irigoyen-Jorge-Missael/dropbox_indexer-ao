# app/main.py
import base64
import json
import logging

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.database import init_db 
from app.services.crawler import process_folder_task

# Configure logging
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Dropbox Metadata Indexer",
    description="Fan-out worker for indexing Dropbox metadata",
    version="1.0.0"
)


class PubSubMessage(BaseModel):
    """Pub/Sub push message format."""
    message: dict
    subscription: str = ""


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    logger.info("Initializing Dropbox Metadata Indexer")
    # CORRECCIÓN: Agregamos await porque init_db ahora es async
    await init_db()


@app.get("/health")
async def health_check():
    """Health check endpoint for Cloud Run."""
    return {"status": "healthy", "service": "dropbox-indexer"}


@app.post("/")
async def handle_pubsub_push(request: Request):
    try:
        envelope = await request.json()

        if "message" not in envelope:
            logger.warning("No message field in request")
            raise HTTPException(status_code=400, detail="No message in request")

        pubsub_message = envelope["message"]

        if "data" not in pubsub_message:
            logger.warning("No data field in message")
            raise HTTPException(status_code=400, detail="No data in message")

        message_data = base64.b64decode(pubsub_message["data"]).decode("utf-8")
        payload = json.loads(message_data)

        path = payload.get("path", "/")
        logger.info(f"Received task to process folder: {path}")

        stats = await process_folder_task(path)

        return {
            "status": "success",
            "processed": stats
        }

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in message: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    except Exception as e:
        logger.error(f"Error processing task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/manual")
async def manual_trigger(path: str = "/"):
    logger.info(f"Manual trigger for path: {path}")
    stats = await process_folder_task(path)
    return {"status": "success", "processed": stats}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)