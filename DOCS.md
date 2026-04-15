# Hawi (الحاوي) — Project Documentation

> Last updated: 2026-03-21
> Update this file whenever a major architectural change is made.

Named after al-Razi's 9th-century medical encyclopedia *al-Hawi al-Kabir*.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Tech Stack](#3-tech-stack)
4. [Directory Structure](#4-directory-structure)
5. [Infrastructure Setup](#5-infrastructure-setup)
6. [Pipeline](#6-pipeline)
7. [Backend API](#7-backend-api)
8. [Frontend](#8-frontend)
9. [Configuration Reference](#9-configuration-reference)
10. [Development Workflow](#10-development-workflow)
11. [Data Sources](#11-data-sources)
12. [Current Status](#12-current-status)
13. [RAGAS Evaluation](#13-ragas-evaluation)
14. [Known Limitations](#14-known-limitations)

---

## 1. Project Overview

Hawi is a bilingual (Arabic/English) RAG (Retrieval-Augmented Generation) chatbot that answers questions about Saudi public health data. It ingests official documents from government entities (MOH, GASTAT), embeds them into a vector database using hybrid dense+sparse search, and uses Claude to generate grounded, cited answers from the retrieved context.

**Core principles:**
- Answers are grounded exclusively in official source documents — no hallucination
- Bilingual: Arabic and English queries and documents supported natively
- Sources are always cited inline with page numbers and document titles
- Guest access (no history) + authenticated access (chat history saved)

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        INGESTION PIPELINE                    │
│                                                             │
│  Scraper (MOH / GASTAT)                                     │
│      │  downloads PDFs and xlsx, registers in catalog DB    │
│      ▼                                                      │
│  Parser (pdf_parser / excel_parser)                         │
│      │  extracts structured text, handles tables            │
│      ▼                                                      │
│  Arabic Normalizer                                          │
│      │  strips diacritics, normalizes alef forms            │
│      ▼                                                      │
│  HierarchicalChunker                                        │
│      │  parent (section) + child (paragraph) chunks         │
│      │  min_paragraph=80 chars; tables kept whole           │
│      ▼                                                      │
│  Embedder (Jina embed-multilingual + fastembed BM25)        │
│      │  1024-dim dense + BM25 sparse → upsert to Qdrant     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                         QDRANT (Vector DB)                   │
│   Collection: saudi_health_hub                              │
│   Vectors: dense (1024-dim) + sparse (BM25)                 │
│   Payload: entity, doc title, page, section, pub_date, etc. │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                       FASTAPI BACKEND                        │
│                                                             │
│  Query → embed with Jina (Redis-cached) + BM25 normalize    │
│      │                                                      │
│      ▼                                                      │
│  Hybrid search: dense prefetch (top 30) + BM25 prefetch     │
│      │  (top 8) → RRF fusion → top 30 candidates            │
│      │  + extra stat search on has_statistics=True          │
│      ▼                                                      │
│  Jina Reranker (multilingual) → top 7 chunks                │
│      ▼                                                      │
│  Year-aware recency boost (if query mentions a year,        │
│      │  matching-year chunks get +0.4 score advantage)      │
│      ▼                                                      │
│  Claude (claude-sonnet-4-6) — strict grounding prompt       │
│      │  streams answer over SSE                             │
│      ▼                                                      │
│  Sources appended, chat saved to Postgres (if authed)       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     NEXT.JS 15 FRONTEND                      │
│   Streaming SSE chat, RTL support, markdown + table render  │
│   Suggested question chips, source chunk preview            │
│   Thumbs up/down feedback, theme ripple animation           │
│   /explore document browser, /login auth page               │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| LLM | Anthropic Claude `claude-sonnet-4-6` | Strict grounding, streaming via SSE |
| Embeddings | Jina AI `jina-embeddings-v3` | 1024-dim, multilingual Arabic+English |
| Sparse/BM25 | fastembed `Qdrant/bm25` | Hybrid search; query normalized before encoding |
| Reranker | Jina AI `jina-reranker-v2-base-multilingual` | Cross-encoder, top 7 from ~30 candidates |
| Vector DB | Qdrant | Dense + sparse (RRF fusion), payload filtering |
| Cache | Redis | Query embedding cache (1h TTL) + Celery broker |
| Relational DB | PostgreSQL | Users, chat sessions, data catalog |
| ORM | SQLAlchemy + Alembic | Migrations managed via Alembic |
| Backend | FastAPI (Python 3.11+) | Async, SSE streaming |
| Frontend | Next.js 15, TypeScript, Tailwind | App Router, RTL support |
| PDF parsing | pdfplumber | Text extraction + table detection |
| Excel parsing | openpyxl + pandas | Merged cell handling, bilingual columns |
| Task queue | Celery + Redis | Scheduled pipeline runs (MOH weekly, GASTAT daily) |

---

## 4. Directory Structure

```
saudi-health-hub/
├── backend/                    FastAPI backend
│   ├── api/routes/
│   │   ├── auth.py             POST /api/auth/register, /login, GET /me
│   │   ├── chat.py             POST /api/chat/stream, /api/chat/eval
│   │   ├── documents.py        GET /api/documents/, /entities
│   │   ├── feedback.py         POST /api/feedback (thumbs up/down)
│   │   └── sessions.py         CRUD /api/sessions/
│   ├── models/
│   │   ├── user.py             User model (JWT auth)
│   │   ├── chat.py             ChatSession, ChatMessage models
│   │   └── feedback.py         Feedback model (message_id, rating, comment)
│   ├── services/
│   │   ├── rag.py              RAG orchestration, system prompt, streaming
│   │   └── retrieval.py        Hybrid Qdrant search + Jina embed/rerank
│   ├── config.py               Pydantic settings
│   └── main.py                 FastAPI app, lifespan, CORS
│
├── pipeline/                   Data ingestion pipeline
│   ├── run_pipeline.py         CLI entry point (--entity MOH|GASTAT|--all --force)
│   ├── config.py               Pipeline Pydantic settings
│   ├── catalog/
│   │   └── models.py           Document, DataSource, DocumentChunk models
│   ├── ingestion/
│   │   ├── scrapers/
│   │   │   ├── moh.py          MOH scraper
│   │   │   └── gastat.py       GASTAT scraper (search-based discovery)
│   │   ├── parsers/
│   │   │   ├── pdf_parser.py   Text + table extraction via pdfplumber
│   │   │   └── excel_parser.py Tier 1/2/3 parser (simple/multilevel/bilingual)
│   │   └── processors/
│   │       ├── chunker.py      HierarchicalChunker (parent + child, min 80 chars)
│   │       └── arabic_normalizer.py  Strip diacritics, normalize alef forms
│   ├── embeddings/
│   │   └── embedder.py         Jina dense + BM25 sparse → Qdrant upsert
│   ├── scripts/
│   │   └── add_sparse_vectors.py  Backfill BM25 sparse vectors on existing points
│   ├── seeds/
│   │   └── seed_all.py         Seeds DataSource records for all entities
│   └── eval/
│       ├── golden_dataset.json 38 Q&A pairs (MOH + GASTAT, AR + EN)
│       ├── run_eval.py         RAGAS evaluation runner (with caching)
│       ├── cache/              Cached RAG outputs (avoids re-hitting backend)
│       └── results/            Timestamped JSON eval reports
│
├── frontend/                   Next.js 15 app
│   └── src/
│       ├── app/                Pages (/, /explore, /login, /chat)
│       ├── components/
│       │   ├── ChatInterface.tsx  Chat UI, suggested chips, feedback buttons
│       │   └── SourceCard.tsx    Source citation with expandable chunk preview
│       ├── contexts/
│       │   ├── AuthContext.tsx    JWT token management
│       │   └── UIContext.tsx      Theme toggle with ripple animation
│       └── lib/                API client, streaming SSE handler, types
│
├── docker-compose.yml          Full stack in Docker (postgres, qdrant, redis, backend, frontend)
├── .env                        All secrets and config (see §9)
└── DOCS.md                     This file
```

---

## 5. Infrastructure Setup

All services run via Docker Compose. From the project root:

```bash
# Start everything
docker compose up -d

# Verify all services are running
docker compose ps

# Stop
docker compose down
```

| Service | Port | Purpose |
|---------|------|---------|
| PostgreSQL | 5432 (internal) | Relational data (users, chat, catalog) |
| Qdrant | 6333 (HTTP), 6334 (gRPC) | Vector search |
| Redis | 6379 | Embedding cache + Celery broker |
| Backend | 8000 | FastAPI (runs migrations on startup) |
| Frontend | 3000 | Next.js |

**Qdrant dashboard:** http://localhost:6333/dashboard

### Database migrations

Migrations run automatically when the backend container starts (`alembic upgrade head`). To run manually:

```bash
cd pipeline
alembic upgrade head

# Create a new migration after changing models
alembic revision --autogenerate -m "description"
```

---

## 6. Pipeline

### Running the pipeline

```bash
# From project root
pipeline/.venv/Scripts/python.exe -m pipeline.run_pipeline --entity MOH
pipeline/.venv/Scripts/python.exe -m pipeline.run_pipeline --entity GASTAT

# Force re-process already-completed documents (e.g. after chunker changes)
pipeline/.venv/Scripts/python.exe -m pipeline.run_pipeline --entity GASTAT --force
```

### Pipeline stages

**Stage 1 — Scrape**

Each entity has a scraper that discovers document URLs, downloads files, and registers them in the catalog DB with status `PENDING`. Already-downloaded unchanged files are skipped (hash comparison).

- **MOH**: Parses the publications index HTML page
- **GASTAT**: Search-based discovery — queries `/en/search?q={keyword}` for 20 health terms, extracts `/en/w/` publication page URLs

**Stage 2 — Parse**

- **PDF** (`pdf_parser.py`): Uses `pdfplumber`. Heading detection via font-size. Tables extracted as pipe-separated rows. Chart noise filter, TOC page filter, boilerplate filter applied.
- **Excel** (`excel_parser.py`): Three-tier parser:
  - Tier 1 (simple): Straightforward tabular data
  - Tier 2 (multilevel headers): Flattens multi-row headers
  - Tier 3 (bilingual): Detects Arabic/English column pairs, creates `_ar`/`_en` schema

**Stage 3 — Arabic normalization**

Applied to all text before embedding: strips tashkeel (diacritics), normalizes alef forms (أ إ آ → ا), removes tatweel.

**Stage 4 — Chunking** (`HierarchicalChunker`)

Creates two levels of chunks per section:
- **Parent chunk**: Full section text (stored for context, excluded from retrieval via `parent_index=None`)
- **Child chunks**: Individual paragraphs (min 80 chars; `parent_index >= -1` are retrievable)

Tables detected by pipe-delimiter ratio are kept whole (never split mid-row) and flagged `is_table_description=True`.

Each chunk carries: `page_number`, `section_heading`, `language`, `has_statistics`, `is_table_description`, `parent_index`, `chunk_index`.

**Stage 5 — Embedding**

- **Dense**: Jina `jina-embeddings-v3` (1024-dim). Batches of 96. Retry with exponential backoff on 429.
- **Sparse**: fastembed `Qdrant/bm25`. BM25 computed from `section_heading + content_normalized`.

**Stage 6 — Qdrant upsert**

Each chunk becomes a Qdrant point with dense + sparse vectors and a full metadata payload.

### Scheduled pipeline (Celery)

Celery beat runs scheduled ingestion:
- **MOH**: Weekly on Monday at 06:00 Asia/Riyadh
- **GASTAT**: Daily at 07:00 Asia/Riyadh

---

## 7. Backend API

Start locally (outside Docker):
```bash
cd backend && .venv/Scripts/uvicorn main:app --reload --port 8000
```

In production, the Docker container runs: `alembic upgrade head && uvicorn backend.main:app`.

### Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/auth/register` | — | Create account |
| `POST` | `/api/auth/login` | — | Get JWT token |
| `GET` | `/api/auth/me` | JWT | Current user info |
| `POST` | `/api/chat/stream` | Optional | SSE streaming chat answer |
| `POST` | `/api/chat/eval` | — | Non-streaming answer for RAGAS eval |
| `POST` | `/api/feedback` | Optional | Thumbs up/down rating on a message |
| `GET` | `/api/documents/` | — | Paginated document list with filters |
| `GET` | `/api/documents/entities` | — | Entity summary cards |
| `GET` | `/api/sessions/` | JWT | List user's chat sessions |
| `POST` | `/api/sessions/` | JWT | Create new session |
| `GET` | `/api/sessions/{id}` | JWT | Session with full message history |
| `DELETE` | `/api/sessions/{id}` | JWT | Delete session |
| `GET` | `/health` | — | Simple status |
| `GET` | `/health/full` | — | Checks Qdrant + Jina + Anthropic |

### RAG retrieval flow

1. Query embedding via Jina (Redis-cached 1h) + BM25 sparse vector (Arabic-normalized)
2. **Hybrid Qdrant search**: dense prefetch (top 30) + BM25 prefetch (top 8) → RRF fusion
3. Filter: child chunks only (`parent_index >= -1`); optional entity/doc_type filter
4. Statistical queries get a second search on `has_statistics=True` chunks merged in
5. Jina reranker trims to `top_n=7`
6. **Year-aware boost**: if query mentions a year, chunks from that year get +0.4 score; otherwise recency weight=0.25 applied
7. Context built with `[Source: title]\n[Section: heading]\ncontent` per chunk
8. Claude generates streamed answer; sources appended as final SSE event

### System prompt design

- Answer **only** from provided context (no training knowledge for health facts)
- If exact match not found: provide closest available info, notify user explicitly
- Respond in the **same language as the query**
- Mirror source format: if source uses bullets/tables, replicate that structure
- Always cite sources inline: `[1]`, `[2]`, etc.

---

## 8. Frontend

```bash
cd frontend && npm run dev    # → http://localhost:3000
```

### Pages

| Route | Description |
|-------|-------------|
| `/` | Landing page |
| `/chat` | Main chat interface |
| `/explore` | Document browser — entity cards, search, doc type filter, pagination |
| `/login` | Register / Login form (tabs) |

### Key features

- **Streaming**: SSE events from `/api/chat/stream` rendered incrementally
- **Markdown rendering**: Tables, bullet lists, bold rendered from Claude output
- **RTL support**: Arabic text blocks render right-to-left
- **Suggested questions**: Clickable chips in empty state (bilingual, grounded in indexed content)
- **Source chunk preview**: Expandable excerpt per source card (chevron toggle)
- **Thumbs feedback**: Up/down buttons on assistant messages → `POST /api/feedback`
- **Theme toggle**: Light/dark with circle-expand ripple animation from click point (View Transitions API)
- **Auth state**: JWT in context; unauthenticated users can chat (no history saved)

---

## 9. Configuration Reference

All config in `.env` at project root. Both `backend/` and `pipeline/` load it via Pydantic settings.

```env
# Database
DATABASE_URL=postgresql://sahub:sahub_dev@postgres:5432/saudi_health_hub

# Vector DB
QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=saudi_health_hub

# Cache / Task queue
REDIS_URL=redis://redis:6379

# AI
ANTHROPIC_API_KEY=sk-ant-...
JINA_API_KEY=jina_...

# Auth
JWT_SECRET=change-me-in-production
NEXTAUTH_SECRET=...
NEXTAUTH_URL=http://localhost:3000

# Backend
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
CORS_ORIGINS=http://localhost:3000
```

### Key tunable parameters (`backend/config.py`)

| Parameter | Current | Effect |
|-----------|---------|--------|
| `retrieval_top_k` | 30 | Qdrant candidates before reranking |
| `rerank_top_n` | 7 | Chunks passed to Claude after reranking |
| `use_hybrid_search` | `True` | Enable dense+BM25 RRF fusion |
| `embed_cache_ttl` | 3600 | Redis TTL for query embeddings (seconds) |
| `llm_model` | `claude-sonnet-4-6` | Claude model for answers |

### Key tunable parameters (`pipeline/config.py`)

| Parameter | Current | Effect |
|-----------|---------|--------|
| `embedding_model` | `jina-embeddings-v3` | Jina embed model |
| `bm25_model` | `Qdrant/bm25` | fastembed sparse model |
| `embedding_batch_size` | 96 | Chunks per Jina API call |
| `chunk_size` | 512 | Target chars per child chunk |
| `chunk_overlap` | 64 | Overlap between child chunks |

### Key tunable parameters (`backend/services/retrieval.py`)

| Parameter | Current | Effect |
|-----------|---------|--------|
| `sparse_limit` | `min(fetch_limit, 8)` | BM25 candidates in hybrid search |
| `RECENCY_WEIGHT` | 0.25 | Boost for newest doc in general queries |
| Year boost | +0.4 | Applied when query explicitly names a year |

---

## 10. Development Workflow

### Full local setup from scratch

```bash
# 1. Start all services
docker compose up -d

# 2. Seed data sources (first time only)
pipeline/.venv/Scripts/python.exe -m pipeline.seeds.seed_all

# 3. Run pipeline
pipeline/.venv/Scripts/python.exe -m pipeline.run_pipeline --entity MOH
pipeline/.venv/Scripts/python.exe -m pipeline.run_pipeline --entity GASTAT
```

The backend container handles migrations automatically on startup.

### After changing chunker or retrieval settings

```bash
# Re-index the affected entity
pipeline/.venv/Scripts/python.exe -m pipeline.run_pipeline --entity GASTAT --force

# Rebuild backend after code changes
docker compose build backend && docker compose up -d backend
```

### Running RAGAS evaluation

Backend must be running (`docker compose up -d`):

```bash
cd pipeline/

# Fresh run (hits backend, caches RAG outputs, then scores)
.venv/Scripts/python.exe eval/run_eval.py \
  --cache eval/cache/38q.json \
  --refresh-cache \
  --output results/vN.json \
  --judge claude-sonnet-4-6

# Re-score from cache (zero backend cost)
.venv/Scripts/python.exe eval/run_eval.py \
  --cache eval/cache/38q.json \
  --output results/vN_rescore.json \
  --judge claude-haiku-4-5-20251001
```

**Judge calibration**: Haiku FA is consistently ~0.07 lower than Sonnet; use Haiku for quick iteration, Sonnet for official benchmarks.

---

## 11. Data Sources

### Ministry of Health (MOH)

- **Base URL:** https://www.moh.gov.sa/en/Ministry/Statistics/book/
- **Scraping strategy:** HTML parsing of the publications index page
- **Documents:** Statistical Yearbooks 2021–2024, clinical guidelines, protocol documents
- **Formats:** PDF, xlsx
- **Qdrant vectors:** ~10,000 chunks

### General Authority for Statistics (GASTAT)

- **Base URL:** https://www.stats.gov.sa
- **Scraping strategy:** Search-based discovery — queries `/en/search?q={keyword}` for 20 health terms, extracts `/en/w/` publication page URLs
- **Health search terms:** health, healthcare, hospital, medical, disease, disability, maternal, nutrition, mental, obesity, vaccination, nurse, physician, pharmaceutical, mortality, reproductive, women health, household survey, birth, dental
- **Documents:** Disability 2023, Health Care 2023, Health Determinants 2023, Health Status 2023/2025, Healthcare Statistics 2025, Women Health 2023/2025, Health Safety at Work 2023, Persons with Disability 2023
- **Formats:** PDF, xlsx (magic-byte validation applied — GASTAT sometimes serves HTML with .xlsx extension)
- **Qdrant vectors:** ~4,000 chunks

---

## 12. Current Status

### What is built and working

- **Auth**: JWT backend + React context + `/login` page
- **Chat**: SSE streaming, markdown+table rendering, cited-only sources, Arabic+English
- **Document explorer**: `/explore` — entity cards, search, doc type filter, pagination
- **Suggested questions**: Clickable chips in empty state
- **Source chunk preview**: Expandable excerpt per source card
- **Thumbs feedback**: Up/down on assistant messages → stored in DB
- **Hybrid search**: Dense + BM25 RRF fusion, year-aware recency boost
- **Celery pipeline**: Scheduled MOH (weekly) + GASTAT (daily) ingestion
- **RAGAS eval**: 38-question golden dataset, caching system, Sonnet/Haiku judge options

### RAGAS scores (v30, 38 questions, Sonnet judge)

| Metric | Score | Target |
|--------|-------|--------|
| Faithfulness | **0.921** | >0.85 ✓ |
| Context Precision | **0.799** | >0.75 ✓ |
| Context Recall | **0.955** | >0.70 ✓ |

---

## 13. RAGAS Evaluation

### Golden dataset

38 bilingual questions (`pipeline/eval/golden_dataset.json`) covering MOH and GASTAT content. Questions with exhaustive per-region ground truths or data not present in indexed documents were excluded.

### Metrics

| Metric | Checks | Target |
|--------|--------|--------|
| **Faithfulness** | Answer is grounded in retrieved context | >0.85 |
| **Context Precision** | Retrieved chunks are relevant (no noise) | >0.75 |
| **Context Recall** | Ground-truth info is in retrieved chunks | >0.70 |

### Version history

| Version | Questions | FA | CP | CR | Notes |
|---------|-----------|----|----|-----|-------|
| v5 | 15 | 0.801 | 0.579 | 0.718 | Dense-only baseline |
| v23 | 30 | 0.868 | 0.783 | 0.906 | Hybrid search + Sonnet judge |
| v25 | 30 | 0.942 | 0.772 | 0.897 | Post vertical-header re-index |
| v28 | 47 | 0.865 | 0.659 | 0.752 | Expanded dataset (47q) |
| v29 | 38 | 0.896 | 0.775 | 0.959 | min_paragraph=80, top-k=7, sparse=8 |
| **v30** | **38** | **0.921** | **0.799** | **0.955** | Year boost + Arabic BM25 norm + recency 0.25 |

---

## 14. Known Limitations

### Retrieval

- **Multi-year overlap (Q7)**: Arabic training statistics 2023 still partially retrieves 2021/2022 chunks despite year boost (cp=0.50). Root cause: identical table structure across yearbooks — year appears in surrounding prose but not chunk heading.
- **Co-located sub-tables (Q13, Q14, Q30)**: Dentist, cardiac cath, and nurse data live inside combined "healthcare staff" or "surgical procedures" tables. The section heading doesn't name the sub-topic, so BM25 can't distinguish from adjacent rows. Fix requires parser-level sub-table splitting.
- **Arabic PHC by region (Q33)**: Section heading doesn't surface "مراكز الرعاية الأولية" specifically enough for BM25.

### PDF parsing

- Text-based PDFs only — no OCR for scanned documents.
- Complex nested tables or multi-page tables may produce incomplete pipe-delimited output.
- Heading detection is heuristic (font-size + pattern matching).

### Excel parsing

- Duplicate column names cause pandas to silently drop one column (affects some bilingual yearbook sheets).
- Very wide sheets (100+ columns) produce unwieldy natural-language rows.

### Embeddings

- **Model lock-in**: Switching embedding models requires wiping and re-embedding the entire Qdrant collection.
- **Arabic dialect**: Embeddings trained on MSA. Gulf/Saudi dialect queries may underperform.
- **Jina free tier**: 1M tokens/month. Full corpus re-embed (~10M tokens) requires paid tier.

### Scalability

- Pipeline runs synchronously per document. Large PDFs block the process during re-index.
- Celery worker handles scheduled runs but not concurrent document processing.
