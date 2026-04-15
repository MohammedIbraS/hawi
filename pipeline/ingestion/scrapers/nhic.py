"""
NHIC (National Health Information Center) scraper.

nhic.gov.sa is a JavaScript SPA — all content is rendered client-side and there
is no crawlable HTML document listing. PDF report URLs are hardcoded in the
JS bundle under the /Reports route.

Discovery strategy: direct_urls (from scrape_config)
  - The seed maintains an explicit list of known PDF URLs in scrape_config["direct_urls"].
  - The scraper downloads each URL directly without any index page fetch.
  - When NHIC publishes a new report, add the URL to the seed and re-run seed_nhic.py.
"""
import hashlib
import re
import time
from pathlib import Path
from datetime import datetime, timezone

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from pipeline.catalog.models import DataSource, Document, DocType, IngestStatus
from pipeline.ingestion.scrapers._utils import http_get_with_retry


DOWNLOAD_DIR = Path(__file__).parent.parent.parent / "downloads" / "nhic"

REQUEST_DELAY = 0.5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SaudiHealthHub/1.0; "
        "research bot for open government data aggregation)"
    ),
    "Accept": "application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    "Referer": "https://nhic.gov.sa/Reports",
}


class NHICScraper:
    def __init__(self, session: Session, source: DataSource):
        self.session = session
        self.source = source
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    def run(self) -> list[Document]:
        """
        Download known NHIC report PDFs and register new/updated documents.
        URLs come from scrape_config["direct_urls"] — maintained in seed_nhic.py.
        """
        direct_urls: list[str] = self.source.scrape_config.get("direct_urls", [])
        if not direct_urls:
            logger.warning("NHIC: no direct_urls in scrape_config — nothing to do")
            return []

        logger.info(f"Starting NHIC scrape ({len(direct_urls)} direct URL(s))")

        new_or_updated: list[Document] = []
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=60) as client:
            for url in direct_urls:
                doc = self._process_url(client, url)
                if doc:
                    new_or_updated.append(doc)
                time.sleep(REQUEST_DELAY)

        self.session.flush()
        logger.info(f"NHIC scrape complete. {len(new_or_updated)} new/updated documents.")
        return new_or_updated

    def _process_url(self, client: httpx.Client, url: str) -> Document | None:
        existing: Document | None = (
            self.session.query(Document).filter_by(original_url=url).first()
        )

        try:
            content, checksum = self._download(client, url)
        except Exception as e:
            logger.warning(f"NHIC: failed to download {url}: {e}")
            return None

        if existing:
            if existing.checksum == checksum:
                logger.debug(f"NHIC: unchanged: {url}")
                return None
            existing.checksum = checksum
            existing.ingest_status = IngestStatus.PENDING
            existing.last_fetched_at = datetime.now(timezone.utc)
            logger.info(f"NHIC: updated: {url}")
            return existing

        # Derive a human-readable title from the filename
        raw_name = Path(url).stem
        # URL-decode percent-encoded Arabic/spaces
        from urllib.parse import unquote
        title = unquote(raw_name).replace("_", " ").replace("-", " ").strip()
        is_arabic = _is_arabic_text(title)

        filename = _safe_filename(url)
        file_path = DOWNLOAD_DIR / filename
        file_path.write_bytes(content)

        doc = Document(
            source_id=self.source.id,
            title_ar=title if is_arabic else "",
            title_en=title if not is_arabic else "",
            original_url=url,
            doc_type=DocType.PDF_TEXT,
            file_path=str(file_path),
            checksum=checksum,
            file_size_bytes=len(content),
            ingest_status=IngestStatus.PENDING,
            last_fetched_at=datetime.now(timezone.utc),
        )
        self.session.add(doc)
        logger.info(f"NHIC: new document: {title} [{url}]")
        return doc

    def _download(self, client: httpx.Client, url: str) -> tuple[bytes, str]:
        response = http_get_with_retry(client, url)
        response.raise_for_status()
        content = response.content
        checksum = hashlib.sha256(content).hexdigest()
        return content, checksum


def _is_arabic_text(text: str) -> bool:
    arabic_chars = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
    return arabic_chars / max(len(text), 1) > 0.3


def _safe_filename(url: str) -> str:
    from urllib.parse import unquote
    name = unquote(Path(url).name)
    name = re.sub(r"[^\w\-.]", "_", name)
    return name[:200] or "document"
