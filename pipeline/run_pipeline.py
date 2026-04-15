"""
Main pipeline entry point.

Usage:
  python -m pipeline.run_pipeline --entity MOH
  python -m pipeline.run_pipeline --entity GASTAT
  python -m pipeline.run_pipeline --all
"""
import argparse
from loguru import logger

from pipeline.catalog.database import init_db, get_session
from pipeline.catalog.models import DataSource, Document, DocumentChunk, IngestStatus, EntityName, DocType
from pipeline.ingestion.scrapers.moh import MOHScraper
from pipeline.ingestion.scrapers.gastat import GASTATScraper
from pipeline.ingestion.scrapers.nhic import NHICScraper
from pipeline.ingestion.scrapers.shc import SHCScraper
from pipeline.ingestion.scrapers.sfda import SFDAScraper
from pipeline.ingestion.scrapers.schs import SCHSScraper
from pipeline.ingestion.scrapers.cchi import CCHIScraper
from pipeline.ingestion.scrapers.weqaya import WEQAYAScraper
from pipeline.ingestion.parsers.pdf_parser import parse_pdf, parse_pdf_ocr, is_scanned_pdf
from pipeline.ingestion.parsers.excel_parser import parse_excel
from pipeline.ingestion.processors.chunker import HierarchicalChunker
from pipeline.embeddings.embedder import Embedder
from pipeline.config import get_settings
from pathlib import Path


SCRAPER_MAP = {
    EntityName.MOH: MOHScraper,
    EntityName.GASTAT: GASTATScraper,
    EntityName.NHIC: NHICScraper,
    EntityName.SHC: SHCScraper,
    EntityName.SFDA: SFDAScraper,
    EntityName.SCHS: SCHSScraper,
    EntityName.CCHI: CCHIScraper,
    EntityName.WEQAYA: WEQAYAScraper,
}


def run_entity(entity: EntityName, force: bool = False) -> None:
    settings = get_settings()
    chunker = HierarchicalChunker(
        chunk_size=settings.chunk_size,
        overlap=settings.chunk_overlap,
    )
    embedder = Embedder()
    try:
        # Phase 1: Scrape — register new/updated documents in their own committed session
        with get_session() as session:
            source = session.query(DataSource).filter_by(entity=entity).first()
            if not source:
                logger.error(f"No DataSource found for entity {entity}. Seed the database first.")
                return

            ScraperClass = SCRAPER_MAP.get(entity)
            if not ScraperClass:
                logger.error(f"No scraper implemented for {entity}")
                return

            scraper = ScraperClass(session=session, source=source)
            scraper.run()
            source_id = source.id
        # Session commits here — documents are now in the DB

        # Phase 2: Collect document IDs to process
        with get_session() as session:
            if force:
                # Reset all completed/failed docs back to PENDING so they re-embed
                reset_count = (
                    session.query(Document)
                    .filter(
                        Document.source_id == source_id,
                        Document.ingest_status.in_([IngestStatus.COMPLETED, IngestStatus.FAILED]),
                    )
                    .update({"ingest_status": IngestStatus.PENDING}, synchronize_session=False)
                )
                logger.info(f"--force: reset {reset_count} documents to PENDING for re-indexing")

            pending_ids = [
                doc.id for doc in session.query(Document)
                .filter_by(source_id=source_id, ingest_status=IngestStatus.PENDING)
                .all()
            ]

        logger.info(f"Processing {len(pending_ids)} pending documents for {entity}")

        # Phase 3: Each document gets its own session — one failure won't poison others
        completed, failed = 0, 0
        for doc_id in pending_ids:
            try:
                with get_session() as session:
                    doc = session.query(Document).filter_by(id=doc_id).first()
                    if doc:
                        _process_document(doc, session, chunker, embedder)
                        if doc.ingest_status == IngestStatus.COMPLETED:
                            completed += 1
                        else:
                            failed += 1
            except Exception as e:
                failed += 1
                logger.error(f"Unhandled error for doc {doc_id}: {e}")

        logger.info(f"Done. {completed} completed, {failed} failed.")
    finally:
        embedder.close()


def _process_document(
    doc: Document,
    session,
    chunker: HierarchicalChunker,
    embedder: Embedder,
) -> None:
    logger.info(f"Processing: {doc.original_url}")
    doc.ingest_status = IngestStatus.PROCESSING
    session.flush()

    try:
        # Collect existing chunk IDs upfront but defer Qdrant deletion until after
        # parsing succeeds — if we delete Qdrant points early and parsing then fails,
        # the DB rolls back (restoring the chunk rows) but Qdrant can't roll back,
        # leaving DB chunks pointing at non-existent vectors.
        old_chunks = session.query(DocumentChunk).filter_by(document_id=doc.id).all()
        old_point_ids = [c.qdrant_point_id for c in old_chunks if c.qdrant_point_id]
        # DB chunk deletion is safe to do early — SQLAlchemy rolls it back on failure.
        if old_chunks:
            session.query(DocumentChunk).filter_by(document_id=doc.id).delete(synchronize_session=False)
            session.flush()

        file_path = Path(doc.file_path)

        if doc.doc_type in (DocType.PDF_TEXT, DocType.PDF_SCANNED):
            if is_scanned_pdf(file_path):
                logger.info(f"Scanned PDF detected, using OCR: {file_path.name}")
                parsed = parse_pdf_ocr(file_path)
            else:
                parsed = parse_pdf(file_path)
            chunks = chunker.chunk_document(parsed)

            db_chunks = []
            for chunk in chunks:
                db_chunk = DocumentChunk(
                    document_id=doc.id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    content_normalized=chunk.content_normalized,
                    language=chunk.language,
                    section_heading=chunk.section_heading,
                    page_number=chunk.page_number,
                    has_statistics=chunk.has_statistics,
                    is_table_description=chunk.is_table_description,
                )
                session.add(db_chunk)
                db_chunks.append(db_chunk)
            session.flush()

            embedder.embed_document_chunks(doc, chunks, db_chunks)

        elif doc.doc_type == DocType.EXCEL:
            # Some government sites (e.g. GASTAT) serve HTML files with a
            # .xlsx extension. Detect this by checking the magic bytes —
            # real OOXML/xlsx files start with PK (ZIP magic: 0x50 0x4B).
            raw = file_path.read_bytes()
            skip_reason = None
            if raw[:2] != b'PK':
                skip_reason = f"Not a ZIP file (magic={raw[:4]!r}) — likely HTML masquerading as Excel"
            else:
                import zipfile
                try:
                    with zipfile.ZipFile(file_path) as zf:
                        names = zf.namelist()
                    if not any(n.startswith("xl/") or n == "[Content_Types].xml" for n in names):
                        skip_reason = f"ZIP file but not OOXML (no xl/ entries) — likely ODS or other format"
                except zipfile.BadZipFile as e:
                    skip_reason = f"Corrupt ZIP: {e}"
            if skip_reason:
                logger.warning(f"Skipping {file_path.name}: {skip_reason}")
                doc.ingest_status = IngestStatus.FAILED
                doc.ingest_error = skip_reason
                session.flush()
                return
            tables = parse_excel(file_path)
            from pipeline.catalog.models import StructuredTable
            from pipeline.ingestion.processors.chunker import Chunk
            all_chunks = []
            all_db_chunks = []
            chunk_index = 0
            for table in tables:
                st = StructuredTable(
                    document_id=doc.id,
                    sheet_name=table.sheet_name,
                    table_index=table.table_index,
                    columns_ar=table.columns_ar,
                    columns_en=table.columns_en,
                    data=table.data,
                    row_count=table.row_count,
                    natural_language_description=table.natural_language_description,
                )
                session.add(st)

                if table.natural_language_description:
                    desc_chunk = Chunk(
                        content=table.natural_language_description,
                        content_normalized=table.natural_language_description,
                        chunk_index=chunk_index,
                        language="en",
                        section_heading=table.sheet_name,
                        is_table_description=True,
                    )
                    db_chunk = DocumentChunk(
                        document_id=doc.id,
                        chunk_index=chunk_index,
                        content=table.natural_language_description,
                        content_normalized=table.natural_language_description,
                        language="en",
                        section_heading=table.sheet_name,
                        is_table_description=True,
                    )
                    session.add(db_chunk)
                    all_chunks.append(desc_chunk)
                    all_db_chunks.append(db_chunk)
                    chunk_index += 1

            session.flush()
            if all_chunks:
                embedder.embed_document_chunks(doc, all_chunks, all_db_chunks)

        # Now safe to delete old Qdrant points — parsing and embedding succeeded.
        if old_point_ids:
            try:
                embedder.delete_document_points(old_point_ids)
                logger.debug(f"Deleted {len(old_point_ids)} old Qdrant points for doc {doc.id}")
            except Exception as e:
                logger.warning(f"Could not delete old Qdrant points for doc {doc.id}: {e}")

        doc.ingest_status = IngestStatus.COMPLETED
        logger.info(f"Completed: {doc.original_url}")

    except Exception as e:
        doc.ingest_status = IngestStatus.FAILED
        doc.ingest_error = str(e)
        session.flush()
        err_str = str(e)
        # Permanent format errors — commit FAILED so we don't retry on every run
        if "does not support" in err_str and "file format" in err_str:
            logger.warning(f"Permanent format error for {doc.original_url}: {e}")
            return  # session commits FAILED status
        logger.error(f"Failed to process {doc.original_url}: {e}")
        raise  # transient error — rollback so doc stays PENDING and retries next run


if __name__ == "__main__":
    init_db()

    parser = argparse.ArgumentParser(description="Run the ingestion pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--entity", type=str, choices=[e.value for e in EntityName])
    group.add_argument("--all", action="store_true")
    parser.add_argument("--force", action="store_true", help="Re-process already-completed documents")
    args = parser.parse_args()

    if args.all:
        for entity in SCRAPER_MAP:
            run_entity(entity, force=args.force)
    else:
        run_entity(EntityName(args.entity), force=args.force)
