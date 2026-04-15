from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from pathlib import Path

router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentSummary(BaseModel):
    id: str
    entity: str
    title_ar: Optional[str]
    title_en: Optional[str]
    doc_type: str
    original_url: str
    publication_date: Optional[datetime]
    last_fetched_at: Optional[datetime]
    ingest_status: str


class DocumentsResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[DocumentSummary]


@router.get("", response_model=DocumentsResponse)
async def list_documents(
    entity: Optional[str] = Query(None),
    doc_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
):
    """Browse all ingested documents with optional filters and search."""
    from backend.database import get_session
    from pipeline.catalog.models import Document, DataSource
    from sqlalchemy.orm import joinedload

    with get_session() as session:
        q = (
            session.query(Document)
            .join(DataSource)
            .options(joinedload(Document.source))
        )
        q = q.filter(Document.ingest_status == "completed")
        if entity:
            q = q.filter(DataSource.entity == entity)
        if doc_type:
            q = q.filter(Document.doc_type == doc_type)
        if search:
            term = f"%{search}%"
            q = q.filter(
                Document.title_en.ilike(term) | Document.title_ar.ilike(term)
            )
        q = q.order_by(Document.last_fetched_at.desc())
        total = q.count()
        docs = q.offset((page - 1) * page_size).limit(page_size).all()

        # Build response inside session while objects are still attached
        items = [
            DocumentSummary(
                id=str(d.id),
                entity=d.source.entity.value if d.source else "",
                title_ar=d.title_ar,
                title_en=d.title_en,
                doc_type=d.doc_type.value if d.doc_type else "",
                original_url=d.original_url,
                publication_date=d.publication_date,
                last_fetched_at=d.last_fetched_at,
                ingest_status=d.ingest_status.value if d.ingest_status else "",
            )
            for d in docs
        ]

    return DocumentsResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/entities")
async def list_entities():
    """Return all active source entities with document counts, freshness, and failure info."""
    from backend.database import get_session
    from pipeline.catalog.models import DataSource, Document
    from sqlalchemy import func, case

    with get_session() as session:
        results = (
            session.query(
                DataSource.entity,
                DataSource.name_ar,
                DataSource.name_en,
                func.count(
                    case((Document.ingest_status == "completed", Document.id))
                ).label("doc_count"),
                func.max(Document.last_fetched_at).label("last_updated"),
                func.count(
                    case((Document.ingest_status == "failed", Document.id))
                ).label("failed_count"),
                func.count(
                    case((Document.ingest_status.in_(["pending", "processing"]), Document.id))
                ).label("pending_count"),
            )
            .filter(DataSource.is_active == True)
            .outerjoin(Document)
            .group_by(DataSource.entity, DataSource.name_ar, DataSource.name_en)
            .all()
        )

    return [
        {
            "entity": r.entity.value,
            "name_ar": r.name_ar,
            "name_en": r.name_en,
            "doc_count": r.doc_count,
            "last_updated": r.last_updated,
            "failed_count": r.failed_count,
            "pending_count": r.pending_count,
        }
        for r in results
    ]


_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
}


@router.get("/{doc_id}/file")
async def serve_document_file(doc_id: str):
    """Stream the locally stored file for a document so the frontend can embed it."""
    from backend.database import get_session
    from pipeline.catalog.models import Document

    with get_session() as session:
        doc = session.query(Document).filter_by(id=doc_id).first()
        if not doc or not doc.file_path:
            raise HTTPException(status_code=404, detail="Document not found")
        file_path = Path(doc.file_path)
        title = doc.title_en or doc.title_ar or file_path.name

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not on disk")

    media_type = _MEDIA_TYPES.get(file_path.suffix.lower(), "application/octet-stream")
    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=file_path.name,
        # inline — tell the browser to display rather than download
        headers={"Content-Disposition": f'inline; filename="{file_path.name}"'},
    )
