"""
Re-index a single document by title (partial match).

Usage (from project root):
    pipeline/.venv/Scripts/python.exe -m pipeline.scripts.reindex_document "UrgentCare"

This resets the document's ingest_status to PENDING, deletes its existing
Qdrant points and DB chunks, then re-parses, re-chunks, and re-embeds it.
Useful after a chunker fix that only affects certain documents.
"""
import sys
import argparse
from loguru import logger

from pipeline.catalog.database import init_db, get_session
from pipeline.catalog.models import Document, DocumentChunk, IngestStatus
from pipeline.ingestion.processors.chunker import HierarchicalChunker
from pipeline.embeddings.embedder import Embedder
from pipeline.config import get_settings
from pipeline.run_pipeline import _process_document


def reindex_by_title(title_fragment: str, dry_run: bool = False) -> None:
    init_db()
    settings = get_settings()

    with get_session() as session:
        docs = (
            session.query(Document)
            .filter(Document.title_en.ilike(f"%{title_fragment}%"))
            .all()
        )
        if not docs:
            logger.error(f"No documents found matching title fragment: {title_fragment!r}")
            sys.exit(1)

        logger.info(f"Found {len(docs)} document(s) matching {title_fragment!r}:")
        for d in docs:
            chunk_count = session.query(DocumentChunk).filter_by(document_id=d.id).count()
            logger.info(f"  [{d.ingest_status}] {d.title_en!r}  ({chunk_count} chunks)")

        if dry_run:
            logger.info("--dry-run: no changes made.")
            return

        # Reset matched docs to PENDING
        for d in docs:
            d.ingest_status = IngestStatus.PENDING
            logger.info(f"Reset to PENDING: {d.title_en!r}")
        session.flush()
        doc_ids = [d.id for d in docs]

    chunker = HierarchicalChunker(
        chunk_size=settings.chunk_size,
        overlap=settings.chunk_overlap,
    )
    embedder = Embedder()

    completed, failed = 0, 0
    for doc_id in doc_ids:
        try:
            with get_session() as session:
                doc = session.query(Document).filter_by(id=doc_id).first()
                if doc:
                    _process_document(doc, session, chunker, embedder)
                    if doc.ingest_status == IngestStatus.COMPLETED:
                        completed += 1
                        logger.info(f"✓ Re-indexed: {doc.title_en!r}")
                    else:
                        failed += 1
                        logger.error(f"✗ Failed: {doc.title_en!r}  error={doc.ingest_error}")
        except Exception as e:
            failed += 1
            logger.error(f"Unhandled error for doc {doc_id}: {e}")

    logger.info(f"Done. {completed} completed, {failed} failed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-index a single document by title fragment")
    parser.add_argument("title", help="Partial document title to match (case-insensitive)")
    parser.add_argument("--dry-run", action="store_true", help="Show matching docs without re-indexing")
    args = parser.parse_args()

    reindex_by_title(args.title, dry_run=args.dry_run)
