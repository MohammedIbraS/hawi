"""
MOH (Ministry of Health) scraper.
Target: https://www.moh.gov.sa/en/Ministry/Statistics/

Fetches the statistical publications index and downloads new/updated documents.
Uses the data catalog to avoid re-downloading unchanged files.
"""
import hashlib
import re
from pathlib import Path
from urllib.parse import urljoin
from datetime import datetime, timezone

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from pipeline.catalog.models import DataSource, Document, DocType, IngestStatus, EntityName
from pipeline.ingestion.scrapers._utils import http_get_with_retry


DOWNLOAD_DIR = Path(__file__).parent.parent.parent / "downloads" / "moh"

MOH_STATS_URL = "https://www.moh.gov.sa/en/Ministry/Statistics/book/Pages/default.aspx"
MOH_BASE_URL = "https://www.moh.gov.sa"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SaudiHealthHub/1.0; "
        "research bot for open government data aggregation)"
    ),
    "Accept-Language": "ar,en;q=0.9",
}


class MOHScraper:
    def __init__(self, session: Session, source: DataSource):
        self.session = session
        self.source = source
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    def run(self) -> list[Document]:
        """
        Scrape the MOH statistics page and register new/updated documents.
        Returns list of Document records created or marked for re-ingestion.
        """
        logger.info(f"Starting MOH scrape from {MOH_STATS_URL}")
        document_links = self._fetch_document_links()
        logger.info(f"Found {len(document_links)} document links")

        new_or_updated: list[Document] = []

        for link_info in document_links:
            doc = self._process_link(link_info)
            if doc:
                new_or_updated.append(doc)

        self.session.flush()
        logger.info(f"MOH scrape complete. {len(new_or_updated)} new/updated documents.")
        return new_or_updated

    def _fetch_document_links(self) -> list[dict]:
        """
        Fetch document links from the MOH statistics index page.
        Returns list of dicts: {url, title_ar, title_en, doc_type}
        """
        links = []
        try:
            with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
                response = client.get(MOH_STATS_URL)
                response.raise_for_status()
                html = response.text

            # Extract all PDF and Excel links from the page
            # Pattern matches href attributes pointing to documents
            href_pattern = re.compile(
                r'href=["\']([^"\']*\.(?:pdf|xlsx?|xls))["\']',
                re.IGNORECASE,
            )
            title_pattern = re.compile(r'>([^<]{5,120})</a>', re.IGNORECASE)

            for match in href_pattern.finditer(html):
                href = match.group(1)
                url = urljoin(MOH_BASE_URL, href)
                ext = Path(href).suffix.lower()
                doc_type = DocType.PDF_TEXT if ext == ".pdf" else DocType.EXCEL

                # Try to find associated anchor text
                start = max(0, match.start() - 200)
                context = html[start:match.start()]
                title_match = title_pattern.search(context)
                title = title_match.group(1).strip() if title_match else Path(href).stem

                links.append({
                    "url": url,
                    "title_ar": title if _is_arabic_text(title) else "",
                    "title_en": title if not _is_arabic_text(title) else "",
                    "doc_type": doc_type,
                })

        except httpx.HTTPError as e:
            logger.warning(f"HTTP error while fetching MOH index: {e}")

        return links

    def _process_link(self, link_info: dict) -> Document | None:
        """
        Download the document and create/update a Document record.
        Skips if unchanged (same checksum).
        """
        url = link_info["url"]

        # Check if already in catalog
        existing: Document | None = (
            self.session.query(Document)
            .filter_by(original_url=url)
            .first()
        )

        try:
            content, checksum = self._download(url)
        except Exception as e:
            logger.warning(f"Failed to download {url}: {e}")
            return None

        if existing:
            if existing.checksum == checksum:
                logger.debug(f"Unchanged: {url}")
                return None
            # File changed — mark for re-ingestion
            existing.checksum = checksum
            existing.ingest_status = IngestStatus.PENDING
            existing.last_fetched_at = datetime.now(timezone.utc)
            logger.info(f"Updated: {url}")
            return existing

        # Save file to disk
        filename = _safe_filename(url)
        file_path = DOWNLOAD_DIR / filename
        file_path.write_bytes(content)

        doc = Document(
            source_id=self.source.id,
            title_ar=link_info.get("title_ar") or "",
            title_en=link_info.get("title_en") or "",
            original_url=url,
            doc_type=link_info["doc_type"],
            file_path=str(file_path),
            checksum=checksum,
            file_size_bytes=len(content),
            ingest_status=IngestStatus.PENDING,
            last_fetched_at=datetime.now(timezone.utc),
        )
        self.session.add(doc)
        logger.info(f"New document: {url}")
        return doc

    def _download(self, url: str) -> tuple[bytes, str]:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=60) as client:
            response = http_get_with_retry(client, url)
            response.raise_for_status()
            content = response.content
            checksum = hashlib.sha256(content).hexdigest()
            return content, checksum


def _is_arabic_text(text: str) -> bool:
    arabic_chars = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
    return arabic_chars / max(len(text), 1) > 0.3


def _safe_filename(url: str) -> str:
    name = Path(url).name
    name = re.sub(r"[^\w\-.]", "_", name)
    return name[:200]
