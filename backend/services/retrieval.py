"""
Retrieval service: dense vector search → reranking → context assembly.

Improvements over naive retrieval:
- Child-only search: parent (section) chunks are filtered out — only paragraph-level
  child chunks are searched, which are more focused and precise.
- Redis embedding cache: identical queries skip the Cohere embed call.
- Stat query detection: numeric/statistical queries overfetch and prioritise
  has_statistics=True chunks so the LLM gets data-dense context.
- Retries on transient network failures.
"""
import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

import httpx
import redis.asyncio as aioredis
from fastembed import SparseTextEmbedding
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, Range, Prefetch, SparseVector, FusionQuery, Fusion
from loguru import logger

from backend.config import get_settings
from pipeline.ingestion.processors.arabic_normalizer import normalize_for_embedding

JINA_API = "https://api.jina.ai/v1"
EMBED_MODEL = "jina-embeddings-v3"
RERANK_MODEL = "jina-reranker-v2-base-multilingual"
EMBED_DIMS = 1024
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"

_RETRYABLE = (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError)

# Patterns that suggest a query is asking for statistics / numbers
_STAT_RE = re.compile(
    r"\d[\d,،.٪%]*\s*(?:%|٪|percent|مليون|billion|ألف|thousand|مليار)"
    r"|\b\d{4}\b"
    r"|نسبة|معدل|إجمالي|عدد|ميزانية|budget|rate|ratio|total|count|spending|expenditure",
    re.IGNORECASE,
)

# Chunks that are bibliography/citation entries — never useful as answers
_BIBLIOGRAPHY_RE = re.compile(r"Retrieved from https?://|Retrieved\s+from\s+https?://", re.IGNORECASE)

# Detect explicit page references: "page 96", "صفحة 96", "سفحة 96", "ص 96", "p.96"
_PAGE_RE = re.compile(
    r"(?:page|p\.?|صفحة|سفحة|ص)\s*(\d{1,4})",
    re.IGNORECASE,
)

# Extract a 4-digit year (1990–2099) from a document title like "Statistical-Yearbook-2023"
_TITLE_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")

# Queries that imply "most recent data" without an explicit year.
# English: "latest", "most recent", "current", "last N years", etc.
# Arabic: الأحدث، الأخيرة، الأخير، الحالي، هذا العام، السنوات الأخيرة، حديثاً
_IMPLICIT_RECENT_RE = re.compile(
    r"\b(?:latest|most\s+recent|current|last\s+\d+\s+years?|over\s+the\s+(?:past|last)|this\s+year)\b"
    r"|الأحدث|الأخير[ةه]?|الحالي[ةه]?|هذا\s+العام|السنة\s+الأخيرة|السنوات\s+الأخيرة|في\s+السنوات\s+الأخيرة|حديثاً|حديث",
    re.IGNORECASE,
)

# MOH-entity queries (English + Arabic) — used by sector boost
_MOH_QUERY_RE = re.compile(
    r"\bMOH\b|ministry\s+of\s+health|وزارة\s+الصحة",
    re.IGNORECASE,
)

# Section heading classifiers for sector boost
_PRIVATE_SECTOR_HDG_RE = re.compile(r"private\s+sector|القطاع\s+الخاص", re.IGNORECASE)
_OTHER_GOV_HDG_RE = re.compile(r"other\s+govern|القطاع\s+الحكومي\s+الآخر", re.IGNORECASE)
_MOH_SECTOR_HDG_RE = re.compile(r"\bMoH\b|\bMOH\b|ministry\s+of\s+health|وزارة\s+الصحة", re.IGNORECASE)

# Bilingual term mapping: Arabic query terms → English section heading keywords
# Used to boost chunks whose English section heading matches the semantic intent
# of an Arabic query, helping the reranker when cross-lingual matching is weak.
_AR_EN_HEADING_BOOST: list[tuple[re.Pattern, re.Pattern]] = [
    (re.compile(r"مراكز\s+الرعاية\s+الصحية\s+الأولية|مراكز\s+الرعاية\s+الأولية"),
     re.compile(r"primary\s+health\s+care\s+center", re.IGNORECASE)),
    (re.compile(r"ممرض|ممرضون|ممرضات"),
     re.compile(r"\bnurse", re.IGNORECASE)),
    (re.compile(r"طبيب\s+أسنان|أطباء\s+أسنان|طب\s+الأسنان"),
     re.compile(r"\bdentist", re.IGNORECASE)),
    (re.compile(r"مستشفيات|مستشفى"),
     re.compile(r"\bhospital", re.IGNORECASE)),
    (re.compile(r"أطباء|الأطباء"),
     re.compile(r"\bphysician", re.IGNORECASE)),
]


def extract_page_number(query: str) -> Optional[int]:
    m = _PAGE_RE.search(query)
    return int(m.group(1)) if m else None


async def _retry(coro_fn, retries: int = 2, delay: float = 1.5):
    for attempt in range(retries + 1):
        try:
            return await coro_fn()
        except _RETRYABLE as e:
            if attempt == retries:
                raise
            logger.warning(f"Network error (attempt {attempt + 1}/{retries + 1}): {e}. Retrying…")
            await asyncio.sleep(delay)


@dataclass
class RetrievedChunk:
    content: str
    score: float
    document_id: str
    document_title_ar: str
    document_title_en: str
    original_url: str
    entity: str
    section_heading: Optional[str]
    page_number: Optional[int]
    has_statistics: bool
    is_table_description: bool
    language: str
    publication_date: Optional[str] = None  # ISO date string e.g. "2023-01-01"


class RetrievalService:
    """Singleton — created once at startup, shared across all requests."""

    def __init__(self):
        settings = get_settings()
        self.qdrant = AsyncQdrantClient(url=settings.qdrant_url)
        self._http = httpx.AsyncClient(
            timeout=30,
            headers={
                "Authorization": f"Bearer {settings.jina_api_key}",
                "Content-Type": "application/json",
            },
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=False)
        self._cache_ttl = settings.embed_cache_ttl
        self.collection = settings.qdrant_collection
        self.top_k = settings.retrieval_top_k
        self.rerank_top_n = settings.rerank_top_n
        logger.info("Loading BM25 sparse embedding model...")
        self._bm25 = SparseTextEmbedding(model_name="Qdrant/bm25")

    async def close(self):
        await self._http.aclose()
        await self._redis.aclose()

    async def retrieve(
        self,
        query: str,
        entity_filter: Optional[str] = None,
        doc_type_filter: Optional[str] = None,
    ) -> list[RetrievedChunk]:
        settings = get_settings()
        is_stat_query = bool(_STAT_RE.search(query))
        page_number = extract_page_number(query)
        year_m = _TITLE_YEAR_RE.search(query)
        query_year = int(year_m.group(1)) if year_m else None

        # For queries that explicitly ask for recent data ("latest", "الأحدث", etc.)
        # without naming a year, resolve the implied year from the most recent doc
        # in the candidate set and apply a stepped boost (max→+0.4, max-1→+0.2).
        # For general queries without temporal language, the fractional RECENCY_WEIGHT
        # already gently favours newer docs without displacing good older content.
        prefer_recent = query_year is None and bool(_IMPLICIT_RECENT_RE.search(query))

        # Overfetch for stat queries to ensure enough stat chunks survive reranking
        fetch_limit = self.top_k + 15 if is_stat_query else self.top_k

        query_vector = await self._embed_query(query)
        qdrant_filter = self._build_filter(entity_filter, doc_type_filter, page_number)

        if settings.use_hybrid_search:
            sparse_vector = self._embed_query_sparse(query)
            # Hybrid search: dense (primary) + sparse BM25 (secondary, fewer candidates)
            # Sparse limit is capped lower to avoid BM25 noise drowning semantic results
            sparse_limit = min(fetch_limit, 8)
            results = await self.qdrant.query_points(
                collection_name=self.collection,
                prefetch=[
                    Prefetch(
                        query=query_vector,
                        using=DENSE_VECTOR_NAME,
                        filter=qdrant_filter,
                        limit=fetch_limit,
                    ),
                    Prefetch(
                        query=SparseVector(
                            indices=sparse_vector.indices.tolist(),
                            values=sparse_vector.values.tolist(),
                        ),
                        using=SPARSE_VECTOR_NAME,
                        filter=qdrant_filter,
                        limit=sparse_limit,
                    ),
                ],
                query=FusionQuery(fusion=Fusion.RRF),
                limit=fetch_limit,
                with_payload=True,
            )
            if not results.points:
                return []
            candidates = [self._to_chunk(r) for r in results.points]
            if is_stat_query and page_number is None:
                candidates = await self._merge_stat_candidates(
                    query_vector, sparse_vector, qdrant_filter, candidates
                )
        else:
            # Dense-only search (default)
            results = await self.qdrant.search(
                collection_name=self.collection,
                query_vector=(DENSE_VECTOR_NAME, query_vector),
                query_filter=qdrant_filter,
                limit=fetch_limit,
                with_payload=True,
            )
            if not results:
                return []
            candidates = [self._to_chunk(r) for r in results]
            if is_stat_query and page_number is None:
                candidates = await self._merge_stat_candidates_dense(
                    query_vector, qdrant_filter, candidates
                )

        # Resolve implied year from the most recent doc in the candidate set
        if prefer_recent and query_year is None:
            years = []
            for c in candidates:
                if c.publication_date:
                    try:
                        years.append(date.fromisoformat(c.publication_date[:10]).year)
                    except ValueError:
                        pass
                else:
                    m = _TITLE_YEAR_RE.search(c.document_title_en or "")
                    if m:
                        years.append(int(m.group(1)))
            if years:
                query_year = max(years)
                logger.debug(f"Implicit recent query — using max doc year as query_year={query_year}")

        # Stash prefer_recent so _apply_recency_boost can use stepped boost
        self._prefer_recent = prefer_recent
        return await self._rerank(query, candidates, query_year=query_year)

    def _embed_query_sparse(self, query: str):
        """Compute BM25 sparse vector for a query (synchronous, fast).

        Normalizes Arabic text (strips diacritics, unifies alef forms) to match
        how chunks were indexed — without this, Arabic queries miss BM25 matches.
        """
        return list(self._bm25.query_embed(normalize_for_embedding(query)))[0]

    async def _merge_stat_candidates_dense(
        self,
        query_vector: list[float],
        base_filter: Optional[Filter],
        candidates: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """Dense-only version: run a second search scoped to has_statistics=True and merge new results."""
        try:
            stat_conditions = [FieldCondition(key="has_statistics", match=MatchValue(value=True))]
            if base_filter and base_filter.must:
                stat_conditions = list(base_filter.must) + stat_conditions
            stat_filter = Filter(must=stat_conditions)

            stat_results = await self.qdrant.search(
                collection_name=self.collection,
                query_vector=(DENSE_VECTOR_NAME, query_vector),
                query_filter=stat_filter,
                limit=10,
                with_payload=True,
            )

            existing_ids = {c.document_id + str(c.page_number) for c in candidates}
            for r in stat_results:
                chunk = self._to_chunk(r)
                key = chunk.document_id + str(chunk.page_number)
                if key not in existing_ids:
                    candidates.append(chunk)
                    existing_ids.add(key)
        except Exception as e:
            logger.warning(f"Stat candidate merge failed: {e}")

        return candidates

    async def _merge_stat_candidates(
        self,
        query_vector: list[float],
        sparse_vector,
        base_filter: Optional[Filter],
        candidates: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """Run a second hybrid search scoped to has_statistics=True and merge new results."""
        try:
            stat_conditions = [FieldCondition(key="has_statistics", match=MatchValue(value=True))]
            if base_filter and base_filter.must:
                stat_conditions = list(base_filter.must) + stat_conditions
            stat_filter = Filter(must=stat_conditions)

            stat_results = await self.qdrant.query_points(
                collection_name=self.collection,
                prefetch=[
                    Prefetch(query=query_vector, using=DENSE_VECTOR_NAME, filter=stat_filter, limit=10),
                    Prefetch(
                        query=SparseVector(
                            indices=sparse_vector.indices.tolist(),
                            values=sparse_vector.values.tolist(),
                        ),
                        using=SPARSE_VECTOR_NAME,
                        filter=stat_filter,
                        limit=10,
                    ),
                ],
                query=FusionQuery(fusion=Fusion.RRF),
                limit=10,
                with_payload=True,
            )

            existing_ids = {c.document_id + str(c.page_number) for c in candidates}
            for r in stat_results.points:
                chunk = self._to_chunk(r)
                key = chunk.document_id + str(chunk.page_number)
                if key not in existing_ids:
                    candidates.append(chunk)
                    existing_ids.add(key)
        except Exception as e:
            logger.warning(f"Stat candidate merge failed: {e}")

        return candidates

    async def _embed_query(self, query: str) -> list[float]:
        # Check Redis cache first
        cache_key = f"embed:v1:{hashlib.sha256(query.encode()).hexdigest()}"
        try:
            cached = await self._redis.get(cache_key)
            if cached:
                logger.debug(f"Embedding cache hit for query: {query[:40]}…")
                return json.loads(cached)
        except Exception as e:
            logger.debug(f"Redis cache read failed: {e}")

        # Call Jina
        async def call():
            resp = await self._http.post(
                f"{JINA_API}/embeddings",
                json={
                    "model": EMBED_MODEL,
                    "input": [query],
                    "task": "retrieval.query",
                    "dimensions": EMBED_DIMS,
                },
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]

        vector = await _retry(call)

        # Cache for TTL seconds
        try:
            await self._redis.setex(cache_key, self._cache_ttl, json.dumps(vector))
        except Exception as e:
            logger.debug(f"Redis cache write failed: {e}")

        return vector

    async def _rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        query_year: Optional[int] = None,
    ) -> list[RetrievedChunk]:
        # Strip bibliography/citation entries — they reference other docs but contain no answer
        clean = [c for c in candidates if not _BIBLIOGRAPHY_RE.search(c.content)]
        candidates = clean if clean else candidates  # keep originals if everything matched

        if len(candidates) <= self.rerank_top_n:
            ranked = candidates
        else:
            try:
                async def call():
                    resp = await self._http.post(
                        f"{JINA_API}/rerank",
                        json={
                            "model": RERANK_MODEL,
                            "query": query,
                            "documents": [c.content for c in candidates],
                            "top_n": self.rerank_top_n,
                        },
                    )
                    resp.raise_for_status()
                    return resp.json()["results"]

                results = await _retry(call)
                # Attach reranker scores to chunks so recency/year boost can combine them
                ranked = []
                for r in results:
                    chunk = candidates[r["index"]]
                    chunk.score = r["relevance_score"]
                    ranked.append(chunk)
            except Exception as e:
                logger.warning(f"Reranking failed, using vector scores: {e}")
                ranked = candidates[: self.rerank_top_n]

        ranked = self._apply_sector_boost(ranked, query)
        return self._apply_recency_boost(ranked, query_year=query_year, prefer_recent=getattr(self, '_prefer_recent', False))

    def _apply_sector_boost(
        self,
        chunks: list[RetrievedChunk],
        query: str,
    ) -> list[RetrievedChunk]:
        """
        Two adjustments applied after the Jina reranker:

        1. Sector penalty (MOH queries only):
           When the query mentions MOH, penalise chunks from Private Sector or
           Other Governmental tables so the MOH-specific table wins.
             MOH section heading   → +0.15
             Private / Other-Gov   → −0.20

        2. Bilingual heading boost (Arabic queries):
           When the Arabic query contains a known health term (e.g. PHC centers,
           nurses), boost chunks whose English section heading contains the
           matching English term.  Helps the reranker when cross-lingual matching
           is weak.
             Arabic→English match  → +0.20
        """
        adjusted = []
        for chunk in chunks:
            heading = chunk.section_heading or ""
            delta = 0.0

            # --- Sector penalty (MOH queries) ---
            if _MOH_QUERY_RE.search(query):
                if _PRIVATE_SECTOR_HDG_RE.search(heading):
                    delta -= 0.20
                elif _OTHER_GOV_HDG_RE.search(heading):
                    delta -= 0.20
                elif _MOH_SECTOR_HDG_RE.search(heading):
                    delta += 0.15

            # --- Bilingual heading boost (Arabic queries) ---
            for ar_pat, en_pat in _AR_EN_HEADING_BOOST:
                if ar_pat.search(query) and en_pat.search(heading):
                    delta += 0.20
                    break  # at most one bilingual boost per chunk

            if delta != 0.0:
                logger.debug(
                    f"Query boost {delta:+.2f} for chunk heading: {heading[:60]!r}"
                )
                chunk.score += delta
            adjusted.append(chunk)

        if any(c.score != chunks[i].score for i, c in enumerate(adjusted)):
            return sorted(adjusted, key=lambda c: c.score, reverse=True)
        return adjusted

    def _apply_recency_boost(
        self,
        chunks: list[RetrievedChunk],
        query_year: Optional[int] = None,
        prefer_recent: bool = False,
    ) -> list[RetrievedChunk]:
        """
        Re-sort chunks with a recency bonus so that when two chunks cover the same
        content (e.g. same stat from the 2021 and 2023 Statistical Yearbook), the
        most recent (or year-matching) document wins.

        Three modes:
        - Explicit year query (e.g. "2023"): exact-match boost +0.4 for that year only.
        - Implicit recent query ("latest", "الأحدث", "last N years"): stepped boost —
          max_year → +0.4, max_year-1 → +0.2, older → 0. Prevents a stale yearbook
          from outranking the correct one when a newer year has sparse content.
        - General query (no year, no recency language): standard recency fraction
          with RECENCY_WEIGHT=0.25 — gently favours newer docs without displacing
          older documents that have better content for the specific question.
        """
        RECENCY_WEIGHT = 0.25

        # Parse dates; chunks without a date get the epoch so they sort to the bottom
        def parse_date(chunk: RetrievedChunk) -> date:
            if chunk.publication_date:
                try:
                    return date.fromisoformat(chunk.publication_date[:10])
                except ValueError:
                    pass
            return date.min

        dates = [parse_date(c) for c in chunks]

        if query_year is not None:
            # Implicit-recent mode: stepped boost so second-most-recent year
            # isn't penalised when the newest yearbook has thin coverage.
            if prefer_recent:
                def year_boost(d: date) -> float:
                    if d.year == query_year: return 0.4
                    if d.year == query_year - 1: return 0.2
                    return 0.0
            else:
                # Explicit year in query: exact-match only
                def year_boost(d: date) -> float:
                    return 0.4 if d.year == query_year else 0.0

            boosted = sorted(
                zip(chunks, dates),
                key=lambda t: t[0].score + year_boost(t[1]),
                reverse=True,
            )
            result = [c for c, _ in boosted]
            if chunks and result and result[0].document_id != chunks[0].document_id:
                logger.debug(
                    f"Year boost ({query_year}) reordered top chunk: "
                    f"{chunks[0].document_title_en!r} ({chunks[0].publication_date}) → "
                    f"{result[0].document_title_en!r} ({result[0].publication_date})"
                )
            return result

        unique_dates = sorted(set(dates))
        if len(unique_dates) <= 1:
            return chunks

        # Map each date to a 0–1 fraction (oldest=0, newest=1)
        oldest, newest = unique_dates[0], unique_dates[-1]
        span = (newest - oldest).days or 1  # avoid div-by-zero

        def recency_fraction(d: date) -> float:
            return (d - oldest).days / span

        boosted = sorted(
            zip(chunks, dates),
            key=lambda t: t[0].score + RECENCY_WEIGHT * recency_fraction(t[1]),
            reverse=True,
        )
        result = [c for c, _ in boosted]
        if chunks and result and result[0].document_id != chunks[0].document_id:
            logger.debug(
                f"Recency boost reordered top chunk: {chunks[0].document_title_en!r} "
                f"({chunks[0].publication_date}) → {result[0].document_title_en!r} "
                f"({result[0].publication_date})"
            )
        return result

    def _build_filter(
        self,
        entity: Optional[str],
        doc_type: Optional[str],
        page_number: Optional[int] = None,
    ) -> Optional[Filter]:
        conditions: list = [
            # Only return child chunks — exclude parent chunks (parent_index=None).
            # Child chunks use parent_index >= 0 (pointing to their parent section chunk)
            # OR parent_index = -1 (sentinel for single-paragraph sections with no parent).
            # Parent chunks have parent_index=None and are too large/generic for retrieval.
            FieldCondition(key="parent_index", range=Range(gte=-1)),
        ]
        if entity:
            conditions.append(FieldCondition(key="entity", match=MatchValue(value=entity)))
        if doc_type:
            conditions.append(FieldCondition(key="doc_type", match=MatchValue(value=doc_type)))
        if page_number is not None:
            conditions.append(FieldCondition(key="page_number", match=MatchValue(value=page_number)))
        return Filter(must=conditions)

    def _to_chunk(self, result) -> RetrievedChunk:
        p = result.payload or {}
        # Use stored publication_date; fall back to year extracted from document title
        # so recency boost works even when publication_date wasn't set during indexing.
        pub_date = p.get("publication_date")
        if not pub_date:
            title = p.get("document_title_en", "") or ""
            m = _TITLE_YEAR_RE.search(title)
            if m:
                pub_date = f"{m.group(1)}-01-01"
        return RetrievedChunk(
            content=p.get("content", ""),
            score=result.score,
            document_id=p.get("document_id", ""),
            document_title_ar=p.get("document_title_ar", ""),
            document_title_en=p.get("document_title_en", ""),
            original_url=p.get("original_url", ""),
            entity=p.get("entity", ""),
            section_heading=p.get("section_heading"),
            page_number=p.get("page_number"),
            has_statistics=p.get("has_statistics", False),
            is_table_description=p.get("is_table_description", False),
            language=p.get("language", "unknown"),
            publication_date=pub_date,
        )
