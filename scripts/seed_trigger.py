#!/usr/bin/env python3
"""
Seed Trigger Script

Initiates the Dropbox indexing process by publishing the root folder task
to Pub/Sub. This triggers the fan-out pattern where each folder spawns
new tasks for its subfolders.

Usage:
    python scripts/seed_trigger.py --path "/"
    python scripts/seed_trigger.py --path "/Documents"
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from google.cloud import pubsub_v1

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def publish_seed_task(
    project_id: str,
    topic_name: str,
    path: str
) -> str:
    """
    Publish the initial seed task to Pub/Sub.

    Args:
        project_id: GCP project ID
        topic_name: Pub/Sub topic name
        path: Starting Dropbox path (usually "/" for full index)

    Returns:
        Published message ID
    """
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(project_id, topic_name)

    message_data = json.dumps({"path": path}).encode("utf-8")

    future = publisher.publish(topic_path, message_data)
    message_id = future.result()

    logger.info(f"Published seed task to {topic_name}")
    logger.info(f"  Path: {path}")
    logger.info(f"  Message ID: {message_id}")

    return message_id


def main():
    parser = argparse.ArgumentParser(
        description="Trigger Dropbox indexing process"
    )
    parser.add_argument(
        "--path",
        type=str,
        default="/",
        help="Starting path in Dropbox (default: /)"
    )
    parser.add_argument(
        "--project-id",
        type=str,
        default="nexus-legal-ops",
        help="GCP Project ID"
    )
    parser.add_argument(
        "--topic",
        type=str,
        default="dropbox-crawl-tasks",
        help="Pub/Sub topic name"
    )

    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("Dropbox Metadata Indexer - Seed Trigger")
    logger.info("=" * 50)
    logger.info(f"Project: {args.project_id}")
    logger.info(f"Topic: {args.topic}")
    logger.info(f"Starting path: {args.path}")
    logger.info("=" * 50)

    try:
        message_id = publish_seed_task(
            project_id=args.project_id,
            topic_name=args.topic,
            path=args.path
        )
        logger.info("Seed task published successfully!")
        logger.info("The indexing process will now begin automatically.")
        return 0

    except Exception as e:
        logger.error(f"Failed to publish seed task: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
