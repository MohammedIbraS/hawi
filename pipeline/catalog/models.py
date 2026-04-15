from sqlalchemy import (
    Column, String, Text, DateTime, Boolean,
    Integer, Float, ForeignKey, Enum as SAEnum
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime, timezone
import uuid
import enum


class Base(DeclarativeBase):
    pass


class EntityName(str, enum.Enum):
    MOH = "MOH"
    SFDA = "SFDA"
    SHC = "SHC"
    NHIC = "NHIC"
    GASTAT = "GASTAT"
    SCHS = "SCHS"
    CCHI = "CCHI"
    WEQAYA = "WEQAYA"
    OTHER = "OTHER"


class DocType(str, enum.Enum):
    PDF_TEXT = "pdf_text"
    PDF_SCANNED = "pdf_scanned"
    EXCEL = "excel"
    CSV = "csv"
    HTML = "html"
    WORD = "word"


class IngestStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    STALE = "stale"


class DataSource(Base):
    """Represents a source entity (MOH, SFDA, etc.) and its scrape config."""
    __tablename__ = "data_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity = Column(SAEnum(EntityName), nullable=False)
    name_ar = Column(String(255), nullable=False)
    name_en = Column(String(255), nullable=False)
    base_url = Column(Text, nullable=False)
    scrape_config = Column(JSONB, default={})         # selectors, pagination config
    refresh_interval_hours = Column(Integer, default=24)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    documents = relationship("Document", back_populates="source")


class Document(Base):
    """A single document ingested from a data source."""
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("data_sources.id"), nullable=False)

    title_ar = Column(Text)
    title_en = Column(Text)
    original_url = Column(Text, nullable=False)
    doc_type = Column(SAEnum(DocType, values_callable=lambda x: [e.value for e in x]), nullable=False)
    language = Column(String(10))                     # 'ar', 'en', 'mixed'
    publication_date = Column(DateTime(timezone=True))

    file_path = Column(Text)                          # local path after download
    checksum = Column(String(64))                     # sha256, detect changes
    file_size_bytes = Column(Integer)

    ingest_status = Column(SAEnum(IngestStatus, values_callable=lambda x: [e.value for e in x]), default=IngestStatus.PENDING)
    ingest_error = Column(Text)
    ocr_confidence = Column(Float)                    # null if not scanned

    last_fetched_at = Column(DateTime(timezone=True))
    last_modified_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    source = relationship("DataSource", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    structured_tables = relationship("StructuredTable", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    """A processed text chunk ready for embedding."""
    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)

    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    content_normalized = Column(Text)                 # after Arabic normalization
    language = Column(String(10))

    # Hierarchy
    section_heading = Column(Text)
    parent_chunk_id = Column(UUID(as_uuid=True), ForeignKey("document_chunks.id"))
    page_number = Column(Integer)

    # Flags
    has_statistics = Column(Boolean, default=False)
    is_table_description = Column(Boolean, default=False)

    qdrant_point_id = Column(String(64))              # ID in Qdrant
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    document = relationship("Document", back_populates="chunks")


class StructuredTable(Base):
    """Tabular data extracted from Excel/CSV stored as structured rows."""
    __tablename__ = "structured_tables"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)

    sheet_name = Column(String(255))
    table_index = Column(Integer, default=0)

    # Schema inferred by LLM or detected automatically
    columns_ar = Column(JSONB)                        # [{"name": "المنطقة", "type": "text"}]
    columns_en = Column(JSONB)                        # [{"name": "Region", "type": "text"}]
    row_count = Column(Integer)

    data = Column(JSONB)                              # list of row dicts
    natural_language_description = Column(Text)      # LLM-generated summary

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    document = relationship("Document", back_populates="structured_tables")
