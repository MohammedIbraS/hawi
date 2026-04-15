"""Initial schema: data_sources, documents, document_chunks, structured_tables

Revision ID: 001
Revises:
Create Date: 2026-03-08
"""
from typing import Sequence, Union
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TYPE entityname AS ENUM (
            'MOH', 'SFDA', 'SHC', 'NHIC', 'GASTAT', 'SCHS', 'CCHI', 'WEQAYA', 'OTHER'
        );

        CREATE TYPE doctype AS ENUM (
            'pdf_text', 'pdf_scanned', 'excel', 'csv', 'html', 'word'
        );

        CREATE TYPE ingeststatus AS ENUM (
            'pending', 'processing', 'completed', 'failed', 'stale'
        );

        CREATE TABLE data_sources (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entity      entityname NOT NULL,
            name_ar     VARCHAR(255) NOT NULL,
            name_en     VARCHAR(255) NOT NULL,
            base_url    TEXT NOT NULL,
            scrape_config       JSONB NOT NULL DEFAULT '{}',
            refresh_interval_hours  INTEGER NOT NULL DEFAULT 24,
            is_active   BOOLEAN NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE documents (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id           UUID NOT NULL REFERENCES data_sources(id),
            title_ar            TEXT,
            title_en            TEXT,
            original_url        TEXT NOT NULL,
            doc_type            doctype NOT NULL,
            language            VARCHAR(10),
            publication_date    TIMESTAMPTZ,
            file_path           TEXT,
            checksum            VARCHAR(64),
            file_size_bytes     INTEGER,
            ingest_status       ingeststatus NOT NULL DEFAULT 'pending',
            ingest_error        TEXT,
            ocr_confidence      FLOAT,
            last_fetched_at     TIMESTAMPTZ,
            last_modified_at    TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX ix_documents_source_id      ON documents(source_id);
        CREATE INDEX ix_documents_ingest_status  ON documents(ingest_status);
        CREATE INDEX ix_documents_original_url   ON documents(original_url);

        CREATE TABLE document_chunks (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id         UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index         INTEGER NOT NULL,
            content             TEXT NOT NULL,
            content_normalized  TEXT,
            language            VARCHAR(10),
            section_heading     TEXT,
            parent_chunk_id     UUID REFERENCES document_chunks(id),
            page_number         INTEGER,
            has_statistics      BOOLEAN NOT NULL DEFAULT FALSE,
            is_table_description BOOLEAN NOT NULL DEFAULT FALSE,
            qdrant_point_id     VARCHAR(64),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX ix_chunks_document_id ON document_chunks(document_id);

        CREATE TABLE structured_tables (
            id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id                     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            sheet_name                      VARCHAR(255),
            table_index                     INTEGER NOT NULL DEFAULT 0,
            columns_ar                      JSONB,
            columns_en                      JSONB,
            row_count                       INTEGER,
            data                            JSONB,
            natural_language_description    TEXT,
            created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX ix_structured_tables_document_id ON structured_tables(document_id);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS structured_tables;
        DROP TABLE IF EXISTS document_chunks;
        DROP TABLE IF EXISTS documents;
        DROP TABLE IF EXISTS data_sources;
        DROP TYPE IF EXISTS ingeststatus;
        DROP TYPE IF EXISTS doctype;
        DROP TYPE IF EXISTS entityname;
    """)
