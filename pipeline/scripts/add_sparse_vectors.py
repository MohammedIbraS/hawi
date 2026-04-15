"""
Backfill BM25 sparse vectors onto existing Qdrant points.

Strategy (no Jina API calls needed):
  1. Scroll all existing points, downloading their dense vectors + payload
  2. Delete and recreate the collection with dense + sparse config
  3. Re-upsert every point with the original dense vector + a new BM25 sparse vector

Usage (from project root):
  pipeline\.venv\Scripts\python.exe -m pipeline.scripts.add_sparse_vectors
"""
from loguru import logger
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

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
VECTOR_SIZE = 1024
SCROLL_BATCH = 200
UPSERT_BATCH = 100


def main():
    settings = get_settings()
    qdrant = QdrantClient(url=settings.qdrant_url)
    collection = settings.qdrant_collection

    # ── Step 1: scroll all existing points ───────────────────────────────────
    logger.info("Scrolling all existing Qdrant points (this may take a moment)...")
    all_points = []
    offset = None
    while True:
        results, next_offset = qdrant.scroll(
            collection_name=collection,
            with_vectors=True,
            with_payload=True,
            limit=SCROLL_BATCH,
            offset=offset,
        )
        all_points.extend(results)
        logger.info(f"  Scrolled {len(all_points)} points so far...")
        if next_offset is None:
            break
        offset = next_offset

    logger.info(f"Total points downloaded: {len(all_points)}")
    if not all_points:
        logger.error("No points found in collection. Aborting.")
        return

    # ── Step 2: delete + recreate collection with dense + sparse config ───────
    logger.info("Deleting existing collection...")
    qdrant.delete_collection(collection)

    logger.info("Recreating collection with dense + sparse vector config...")
    qdrant.create_collection(
        collection_name=collection,
        vectors_config={
            DENSE_VECTOR_NAME: VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        },
        sparse_vectors_config={
            SPARSE_VECTOR_NAME: SparseVectorParams(
                index=SparseIndexParams(on_disk=False),
            ),
        },
    )
    logger.info("Collection recreated.")

    # ── Step 3: re-upsert with BM25 sparse vectors added ─────────────────────
    logger.info("Loading BM25 model...")
    bm25 = SparseTextEmbedding(model_name=settings.bm25_model)

    total = len(all_points)
    inserted = 0

    for start in range(0, total, UPSERT_BATCH):
        batch = all_points[start:start + UPSERT_BATCH]
        texts = [p.payload.get("content", "") for p in batch]
        sparse_results = list(bm25.embed(texts))

        new_points = []
        for point, sparse_emb in zip(batch, sparse_results):
            dense_vec = (
                point.vector.get(DENSE_VECTOR_NAME)
                if isinstance(point.vector, dict)
                else point.vector
            )
            new_points.append(PointStruct(
                id=point.id,
                vector={
                    DENSE_VECTOR_NAME: dense_vec,
                    SPARSE_VECTOR_NAME: SparseVector(
                        indices=sparse_emb.indices.tolist(),
                        values=sparse_emb.values.tolist(),
                    ),
                },
                payload=point.payload,
            ))

        qdrant.upsert(collection_name=collection, points=new_points)
        inserted += len(batch)
        logger.info(f"  Re-inserted {inserted}/{total} points...")

    logger.info(f"Done. {inserted} points now have dense + sparse vectors.")


if __name__ == "__main__":
    main()
