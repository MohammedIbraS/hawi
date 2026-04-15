"""
Embeds document chunks and upserts them into Qdrant with full metadata.
Uses Jina embeddings-v3 for Arabic + English support.
Hybrid indexing: dense (semantic) + sparse (BM25 keyword).
"""
import time
import uuid
from typing import Any
from loguru import logger

import httpx
from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    SparseVectorParams,
    SparseIndexParams,
    PointStruct,
    SparseVector,
)

from pipeline.config import get_settings
from pipeline.ingestion.processors.chunker import Chunk
from pipeline.catalog.models import Document, DocumentChunk


DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
VECTOR_SIZE = 1024  # Jina embeddings-v3 output size


JINA_API = "https://api.jina.ai/v1"


class Embedder:
    def __init__(self):
        settings = get_settings()
        self._http = httpx.Client(
            timeout=60,
            headers={
                "Authorization": f"Bearer {settings.jina_api_key}",
                "Content-Type": "application/json",
            },
        )
        self.qdrant = QdrantClient(url=settings.qdrant_url)
        self.collection = settings.qdrant_collection
        self.batch_size = settings.embedding_batch_size
        self.model = settings.embedding_model
        logger.info("Loading BM25 sparse embedding model...")
        self._bm25 = SparseTextEmbedding(model_name=settings.bm25_model)
        self._ensure_collection()

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._http.close()

    def delete_document_points(self, point_ids: list[str]) -> None:
        """Delete Qdrant points by ID (used to clean up before re-indexing)."""
        from qdrant_client.models import PointIdsList
        self.qdrant.delete(
            collection_name=self.collection,
            points_selector=PointIdsList(points=point_ids),
        )

    def embed_document_chunks(
        self,
        document: Document,
        chunks: list[Chunk],
        db_chunks: list[DocumentChunk],
    ) -> None:
        """
        Embed all chunks for a document and upsert into Qdrant.
        Also updates qdrant_point_id on each DocumentChunk record.
        """
        if not chunks:
            return

        # Process in batches
        for i in range(0, len(chunks), self.batch_size):
            batch_chunks = chunks[i:i + self.batch_size]
            batch_db = db_chunks[i:i + self.batch_size]
            self._embed_and_upsert_batch_with_retry(document, batch_chunks, batch_db)
            logger.info(
                f"Embedded batch {i // self.batch_size + 1} "
                f"({len(batch_chunks)} chunks) for doc {document.id}"
            )

    def _embed_and_upsert_batch_with_retry(
        self,
        document: Document,
        chunks: list[Chunk],
        db_chunks: list[DocumentChunk],
        max_retries: int = 6,
    ) -> None:
        """Wrapper that retries _embed_and_upsert_batch on Cohere 429 rate limit errors."""
        delay = 60  # start with 60s wait on first 429 (trial limit resets per minute)
        for attempt in range(max_retries):
            try:
                self._embed_and_upsert_batch(document, chunks, db_chunks)
                return
            except Exception as e:
                if "429" in str(e) or "rate limit" in str(e).lower():
                    if attempt + 1 == max_retries:
                        raise
                    logger.warning(
                        f"Jina rate limit hit (attempt {attempt + 1}/{max_retries}). "
                        f"Waiting {delay}s before retry..."
                    )
                    time.sleep(delay)
                    delay = min(delay * 2, 300)  # cap at 5 minutes
                else:
                    raise

    def _embed_and_upsert_batch(
        self,
        document: Document,
        chunks: list[Chunk],
        db_chunks: list[DocumentChunk],
    ) -> None:
        # Prepend section heading so queries like "مراكز الرعاية الأولية" match the right
        # section even when the raw table content doesn't contain the heading text.
        # Jina's token limit is ~8192 tokens; 6000 chars is a safe character ceiling.
        _MAX_CHARS = 6000
        texts = []
        for c in chunks:
            base = c.content_normalized or c.content
            if c.section_heading:
                text = f"{c.section_heading}\n{base}"
            else:
                text = base
            texts.append(text[:_MAX_CHARS])

        # Get dense embeddings from Jina
        response = self._http.post(
            f"{JINA_API}/embeddings",
            json={
                "model": self.model,
                "input": texts,
                "task": "retrieval.passage",
                "dimensions": VECTOR_SIZE,
            },
        )
        response.raise_for_status()
        data = sorted(response.json()["data"], key=lambda x: x["index"])
        dense_vectors = [item["embedding"] for item in data]

        # Get BM25 sparse embeddings
        sparse_results = list(self._bm25.embed(texts))

        points = []
        for chunk, db_chunk, dense_vec, sparse_emb in zip(chunks, db_chunks, dense_vectors, sparse_results):
            point_id = str(uuid.uuid4())
            db_chunk.qdrant_point_id = point_id

            payload = self._build_payload(document, chunk)

            points.append(PointStruct(
                id=point_id,
                vector={
                    DENSE_VECTOR_NAME: dense_vec,
                    SPARSE_VECTOR_NAME: SparseVector(
                        indices=sparse_emb.indices.tolist(),
                        values=sparse_emb.values.tolist(),
                    ),
                },
                payload=payload,
            ))

        self.qdrant.upsert(collection_name=self.collection, points=points)

    def _build_payload(self, document: Document, chunk: Chunk) -> dict[str, Any]:
        return {
            # Source metadata
            "entity": document.source.entity.value if document.source else None,
            "document_id": str(document.id),
            "document_title_ar": document.title_ar,
            "document_title_en": document.title_en,
            "original_url": document.original_url,
            "doc_type": document.doc_type.value if document.doc_type else None,
            "publication_date": (
                document.publication_date.isoformat()
                if document.publication_date else None
            ),
            # Chunk metadata
            "chunk_index": chunk.chunk_index,
            "language": chunk.language,
            "section_heading": chunk.section_heading,
            "page_number": chunk.page_number,
            "parent_index": chunk.parent_index,
            # Content flags
            "has_statistics": chunk.has_statistics,
            "is_table_description": chunk.is_table_description,
            # Raw content for display (not normalized)
            "content": chunk.content,
        }

    def _ensure_collection(self) -> None:
        """Create the Qdrant collection if it doesn't exist, or add sparse config if missing."""
        existing = [c.name for c in self.qdrant.get_collections().collections]
        if self.collection not in existing:
            self.qdrant.create_collection(
                collection_name=self.collection,
                vectors_config={
                    DENSE_VECTOR_NAME: VectorParams(
                        size=VECTOR_SIZE,
                        distance=Distance.COSINE,
                    ),
                },
                sparse_vectors_config={
                    SPARSE_VECTOR_NAME: SparseVectorParams(
                        index=SparseIndexParams(on_disk=False),
                    ),
                },
            )
            logger.info(f"Created Qdrant collection with dense+sparse: {self.collection}")
            return

        # Collection exists — check if sparse vectors are configured
        info = self.qdrant.get_collection(self.collection)
        has_sparse = (
            info.config.params.sparse_vectors is not None
            and SPARSE_VECTOR_NAME in (info.config.params.sparse_vectors or {})
        )
        if not has_sparse:
            self.qdrant.update_collection(
                collection_name=self.collection,
                sparse_vectors_config={
                    SPARSE_VECTOR_NAME: SparseVectorParams(
                        index=SparseIndexParams(on_disk=False),
                    ),
                },
            )
            logger.info(f"Added sparse vector config to existing collection: {self.collection}")
