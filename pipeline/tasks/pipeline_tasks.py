"""
Celery tasks for the ingestion pipeline.

Main task: scrape_and_index(entity)
  - Runs the full scrape → parse → embed pipeline for a given entity.
  - Idempotent: skips unchanged documents (checksum deduplication).
  - Safe to call manually or via the Beat schedule.

Usage (manual trigger):
    from pipeline.tasks.pipeline_tasks import scrape_and_index
    scrape_and_index.delay("MOH")
    scrape_and_index.delay("GASTAT")
"""
from __future__ import annotations

from loguru import logger

from pipeline.tasks.celery_app import celery_app
from pipeline.run_pipeline import run_entity
from pipeline.catalog.models import EntityName


@celery_app.task(
    bind=True,
    name="pipeline.tasks.pipeline_tasks.scrape_and_index",
    max_retries=3,
    default_retry_delay=300,   # 5 minutes between retries
    acks_late=True,             # only ack after task completes (safe on worker crash)
    queue="pipeline",
)
def scrape_and_index(self, entity_value: str, force: bool = False) -> dict:
    """
    Scrape and index all documents for the given entity.

    Args:
        entity_value: EntityName value string, e.g. "MOH" or "GASTAT".
        force: If True, re-process already-completed documents (full re-index).

    Returns:
        dict with status and entity name.
    """
    try:
        entity = EntityName(entity_value)
    except ValueError:
        logger.error(f"Unknown entity: {entity_value}")
        return {"status": "error", "entity": entity_value, "reason": "unknown entity"}

    logger.info(f"[Celery] Starting scrape_and_index for {entity_value} (force={force})")
    try:
        run_entity(entity, force=force)
        logger.info(f"[Celery] Completed scrape_and_index for {entity_value}")
        return {"status": "ok", "entity": entity_value}
    except Exception as exc:
        logger.error(f"[Celery] scrape_and_index failed for {entity_value}: {exc}")
        raise self.retry(exc=exc)
