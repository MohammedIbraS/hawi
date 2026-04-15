"""Reset zero-chunk SFDA completed docs back to PENDING for re-ingestion."""
from pipeline.catalog.database import get_session
from pipeline.catalog.models import Document, DocumentChunk, IngestStatus, EntityName, DataSource

with get_session() as s:
    source = s.query(DataSource).filter_by(entity=EntityName.SFDA).first()
    if not source:
        print("No SFDA DataSource found.")
        raise SystemExit(1)

    docs = s.query(Document).filter_by(source_id=source.id).all()
    reset = 0
    for d in docs:
        chunk_count = s.query(DocumentChunk).filter_by(document_id=d.id).count()
        if chunk_count == 0 and d.ingest_status.value == "completed":
            d.ingest_status = IngestStatus.PENDING
            print(f"Reset: {d.original_url.split('/')[-1]}")
            reset += 1
    print(f"\nTotal reset: {reset} documents")
