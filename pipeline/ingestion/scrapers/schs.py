"""
SCHS (Saudi Center for Health Statistics) scraper.
Target: https://www.schs.gov.sa/en/statistics/ and /en/publications/

Fetches publication index pages and downloads new/updated PDFs and Excel files.
Uses the data catalog to avoid re-downloading unchanged files.
"""
import hashlib
import re
import time
from pathlib import Path
from urllib.parse import urljoin
from datetime import datetime, timezone

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from pipeline.catalog.models import DataSource, Document, DocType, IngestStatus
from pipeline.ingestion.scrapers._utils import http_get_with_retry


DOWNLOAD_DIR = Path(__file__).parent.parent.parent / "downloads" / "schs"

SCHS_BASE_URL = "https://www.schs.gov.sa"

REQUEST_DELAY = 0.5  # seconds between requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SaudiHealthHub/1.0; "
        "research bot for open government data aggregation)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}


class SCHSScraper:
    def __init__(self, session: Session, source: DataSource):
        self.session = session
        self.source = source
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    def run(self) -> list[Document]:
        """
        Scrape SCHS publication index pages and register new/updated documents.
        Returns list of Document records created or marked for re-ingestion.
        """
        index_urls: list[str] = self.source.scrape_config.get("index_urls", [])
        if not index_urls:
            logger.warning("SCHS: no index_urls configured in scrape_config")
            return []

        logger.info(f"Starting SCHS scrape ({len(index_urls)} index page(s))")

        all_links: list[dict] = []
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
            for url in index_urls:
                links = self._fetch_document_links(client, url)
                logger.info(f"SCHS index {url}: found {len(links)} document links")
                all_links.extend(links)
                time.sleep(REQUEST_DELAY)

        # Deduplicate by URL
        seen: set[str] = set()
        unique_links = []
        for link in all_links:
            if link["url"] not in seen:
                seen.add(link["url"])
                unique_links.append(link)

        logger.info(f"SCHS: {len(unique_links)} unique document links total")

        new_or_updated: list[Document] = []
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=60) as client:
            for link_info in unique_links:
                doc = self._process_link(client, link_info)
                if doc:
                    new_or_updated.append(doc)
                time.sleep(REQUEST_DELAY)

        self.session.flush()
        logger.info(f"SCHS scrape complete. {len(new_or_updated)} new/updated documents.")
        return new_or_updated

    def _fetch_document_links(self, client: httpx.Client, index_url: str) -> list[dict]:
        """
        Fetch document links from a SCHS index page.
        Returns list of dicts: {url, title_ar, title_en, doc_type}
        """
        links = []
        try:
            response = client.get(index_url)
            response.raise_for_status()
            html = response.text
        except httpx.HTTPError as e:
            logger.warning(f"SCHS: HTTP error fetching index {index_url}: {e}")
            return links

        # Extract PDF and Excel links
        href_pattern = re.compile(
            r'href=["\']([^"\']*\.(?:pdf|xlsx?|xls))["\']',
            re.IGNORECASE,
        )

        for match in href_pattern.finditer(html):
            href = match.group(1)
            url = urljoin(SCHS_BASE_URL, href) if not href.startswith("http") else href
            ext = Path(href).suffix.lower().lstrip(".")
            doc_type = DocType.EXCEL if ext in ("xlsx", "xls") else DocType.PDF_TEXT

            # Try to extract title from anchor text surrounding the link
            start = max(0, match.start() - 300)
            context = html[start : match.end() + 100]
            title = _extract_anchor_text(context, match.start() - start) or Path(href).stem

            links.append({
                "url": url,
                "title_ar": title if _is_arabic_text(title) else "",
                "title_en": title if not _is_arabic_text(title) else "",
                "doc_type": doc_type,
            })

        return links

    def _process_link(self, client: httpx.Client, link_info: dict) -> Document | None:
        """
        Download the document and create/update a Document record.
        Skips if unchanged (same checksum).
        """
        url = link_info["url"]

        existing: Document | None = (
            self.session.query(Document).filter_by(original_url=url).first()
        )

        try:
            content, checksum = self._download(client, url)
        except Exception as e:
            logger.warning(f"SCHS: failed to download {url}: {e}")
            return None

        if existing:
            if existing.checksum == checksum:
                logger.debug(f"SCHS: unchanged: {url}")
                return None
            existing.checksum = checksum
            existing.ingest_status = IngestStatus.PENDING
            existing.last_fetched_at = datetime.now(timezone.utc)
            logger.info(f"SCHS: updated: {url}")
            return existing

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
        logger.info(f"SCHS: new document: {link_info.get('title_en') or link_info.get('title_ar') or url}")
        return doc

    def _download(self, client: httpx.Client, url: str) -> tuple[bytes, str]:
        response = http_get_with_retry(client, url)
        response.raise_for_status()
        content = response.content
        checksum = hashlib.sha256(content).hexdigest()
        return content, checksum


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_anchor_text(context: str, link_pos: int) -> str:
    match = re.search(r">([^<]{5,120})</a>", context[:link_pos])
    if match:
        return match.group(1).strip()
    match = re.search(r">([^<]{5,120})</a>", context[link_pos:])
    if match:
        return match.group(1).strip()
    return ""


def _is_arabic_text(text: str) -> bool:
    arabic_chars = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
    return arabic_chars / max(len(text), 1) > 0.3


def _safe_filename(url: str) -> str:
    name = Path(url).name
    name = re.sub(r"[^\w\-.]", "_", name)
    return name[:200] or "document"
