FROM python:3.12-slim

WORKDIR /app

# System deps: libpq for psycopg2-binary, build-essential for fastembed native extensions
# tesseract-ocr + Arabic language pack for scanned PDF OCR; poppler-utils for pdf2image
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    tesseract-ocr \
    tesseract-ocr-ara \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer cache: only re-runs when requirements change)
# Pipeline deps (celery, fastembed, pdfplumber, etc.) are needed by the
# Celery worker which runs in this same image.
COPY backend/requirements.txt backend/requirements.txt
COPY pipeline/requirements.txt pipeline/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt -r pipeline/requirements.txt

# Copy only the packages the backend needs at runtime
# (full pipeline/ is needed for pipeline.catalog.* and pipeline.config imports)
COPY backend/ backend/
COPY pipeline/ pipeline/
COPY shared/ shared/

# fastembed downloads models to ~/.cache/fastembed on first use.
# We pre-download the BM25 model here so startup is instant in production.
RUN python -c "from fastembed import SparseTextEmbedding; SparseTextEmbedding('Qdrant/bm25')"

EXPOSE 8000

# Run alembic migrations then start the server.
# DATABASE_URL is injected by docker-compose at runtime.
CMD ["sh", "-c", "alembic -c pipeline/alembic.ini upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
