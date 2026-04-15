"""
GASTAT (General Authority for Statistics) scraper.

Discovery strategy — search-based:
  1. Query /en/search?q={keyword} for each term in HEALTH_SEARCH_QUERIES
     → each query returns up to 10 /en/w/[slug] URLs
  2. De-duplicate across all queries
  3. For each candidate URL, fetch the detail page and extract
     /documents/... PDF/Excel download links
  4. Download and register in the data catalog

Note: The Liferay sitemap at /sitemap.xml only contains nested sub-sitemap
URLs (with ?p_l_id= params), never actual page URLs — sitemap-based discovery
does not work for this site.
"""
import hashlib
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from datetime import datetime, timezone

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from pipeline.catalog.models import DataSource, Document, DocType, IngestStatus, EntityName
from pipeline.ingestion.scrapers._utils import http_get_with_retry


DOWNLOAD_DIR = Path(__file__).parent.parent.parent / "downloads" / "gastat"

GASTAT_BASE_URL = "https://www.stats.gov.sa"
GASTAT_SEARCH_URL = "https://www.stats.gov.sa/en/search"


# Search queries sent to /en/search?q={term} — each returns up to 10 /en/w/ URLs.
# Together they cover all major health publication topics on the site.
HEALTH_SEARCH_QUERIES = [
    "health", "healthcare", "hospital", "medical", "disease",
    "disability", "maternal", "nutrition", "mental", "obesity",
    "vaccination", "nurse", "physician", "pharmaceutical", "mortality",
    "reproductive", "women health", "household survey", "birth", "dental",
]

REQUEST_DELAY = 0.5   # seconds between requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SaudiHealthHub/1.0; "
        "research bot for open government data aggregation)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}

class GASTATScraper:
    def __init__(self, session: Session, source: DataSource):
        self.session = session
        self.source = source
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    def run(self) -> list[Document]:
        """
        Full pipeline:
          1. Discover health publication URLs via sitemap
          2. Fetch each detail page, extract download links
          3. Download and register new/updated documents
        """
        logger.info("Starting GASTAT scrape (sitemap-based)")

        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
            health_urls = self._discover_health_urls(client)
            logger.info(f"Found {len(health_urls)} health-related publication URLs")

            new_or_updated: list[Document] = []
            for url in health_urls:
                link_info = {
                    "type": "detail_page",
                    "url": url,
                    "slug": _slug_from_url(url),
                    "title_en": _slug_to_title(_slug_from_url(url)),
                    "title_ar": "",
                }
                doc = self._process_detail_page(client, link_info)
                if doc:
                    new_or_updated.append(doc)
                time.sleep(REQUEST_DELAY)

        self.session.flush()
        logger.info(f"GASTAT scrape complete. {len(new_or_updated)} new/updated documents.")
        return new_or_updated

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _discover_health_urls(self, client: httpx.Client) -> list[str]:
        """
        Query /en/search?q={term} for each health keyword and collect all
        /en/w/[slug] URLs returned. Each query returns up to 10 results;
        running ~20 queries covers all major health publication pages.
        """
        seen: set[str] = set()
        health_urls: list[str] = []

        for query in HEALTH_SEARCH_QUERIES:
            try:
                resp = client.get(GASTAT_SEARCH_URL, params={"q": query}, timeout=15)
                resp.raise_for_status()
                # Extract clean /en/w/ URLs (strip query params like p_l_back_url)
                links = re.findall(
                    r'(https://www\.stats\.gov\.sa/en/w/[^"\'?&\s]+)',
                    resp.text,
                )
                new_count = 0
                for url in links:
                    if url not in seen:
                        seen.add(url)
                        health_urls.append(url)
                        new_count += 1
                logger.debug(f"Search '{query}': {len(links)} results, {new_count} new")
            except httpx.HTTPError as e:
                logger.warning(f"Search query '{query}' failed: {e}")
            time.sleep(REQUEST_DELAY)

        return health_urls

    # ------------------------------------------------------------------
    # Detail page processing
    # ------------------------------------------------------------------

    def _process_detail_page(self, client: httpx.Client, link_info: dict) -> Document | None:
        """
        Fetch a GASTAT publication page and extract the primary download link.
        Returns a Document record if a downloadable file was found and
        registered (new or updated), otherwise None.
        """
        detail_url = link_info["url"]
        try:
            resp = client.get(detail_url)
            resp.raise_for_status()
            html = resp.text
        except httpx.HTTPError as e:
            logger.warning(f"Detail page fetch failed ({detail_url}): {e}")
            return None

        # --- Extract title ---
        title_en = link_info.get("title_en", "")
        title_ar = link_info.get("title_ar", "")

        h1_match = re.search(r"<h1[^>]*>([^<]{5,300})</h1>", html, re.IGNORECASE)
        if h1_match:
            raw_title = h1_match.group(1).strip()
            if _is_arabic_text(raw_title):
                title_ar = raw_title
            else:
                title_en = raw_title

        # --- Extract download links ---
        # GASTAT doc URL format: /documents/20117/<id>/<filename>.<ext>/<uuid>?t=<ts>
        doc_pattern = re.compile(
            r'href=["\']((https://www\.stats\.gov\.sa)?/documents/\d+/[^"\'?\s]+\.(?:pdf|xlsx?|xls)/[^"\'?\s]*)(?:\?[^"\']*)?["\']',
            re.IGNORECASE,
        )

        for match in doc_pattern.finditer(html):
            raw_url = match.group(1)
            doc_url = raw_url if raw_url.startswith("http") else urljoin(GASTAT_BASE_URL, raw_url)

            result = self._download_and_register(
                client,
                url=doc_url,
                title_en=title_en,
                title_ar=title_ar,
                doc_type=_doc_type_from_url(doc_url),
                detail_page_url=detail_url,
            )
            if result:
                return result  # one primary file per publication page

        return None

    # ------------------------------------------------------------------
    # Download & catalog
    # ------------------------------------------------------------------

    def _download_and_register(
        self,
        client: httpx.Client,
        url: str,
        title_en: str,
        title_ar: str,
        doc_type: DocType,
        detail_page_url: str | None,
    ) -> Document | None:
        existing: Document | None = (
            self.session.query(Document).filter_by(original_url=url).first()
        )

        try:
            content, checksum = self._download(client, url)
        except Exception as e:
            logger.warning(f"Download failed ({url}): {e}")
            return None

        if existing:
            if existing.checksum == checksum:
                logger.debug(f"Unchanged: {url}")
                return None
            existing.checksum = checksum
            existing.ingest_status = IngestStatus.PENDING
            existing.last_fetched_at = datetime.now(timezone.utc)
            logger.info(f"Updated: {url}")
            return existing

        filename = _safe_filename(url)
        file_path = DOWNLOAD_DIR / filename
        file_path.write_bytes(content)

        doc = Document(
            source_id=self.source.id,
            title_en=title_en,
            title_ar=title_ar,
            original_url=url,
            doc_type=doc_type,
            file_path=str(file_path),
            checksum=checksum,
            file_size_bytes=len(content),
            ingest_status=IngestStatus.PENDING,
            last_fetched_at=datetime.now(timezone.utc),
        )
        self.session.add(doc)
        logger.info(f"New document: {title_en or title_ar} [{url}]")
        return doc

    def _download(self, client: httpx.Client, url: str) -> tuple[bytes, str]:
        resp = http_get_with_retry(client, url, timeout=60)
        resp.raise_for_status()
        content = resp.content
        checksum = hashlib.sha256(content).hexdigest()
        return content, checksum


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_arabic_text(text: str) -> bool:
    arabic_chars = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
    return arabic_chars / max(len(text), 1) > 0.3


def _slug_from_url(url: str) -> str:
    """Extract the slug from a /en/w/[slug] URL."""
    match = re.search(r"/en/w/([^/?#]+)", url)
    return match.group(1) if match else Path(urlparse(url).path).name


def _slug_to_title(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()


def _safe_filename(url: str) -> str:
    """
    GASTAT URLs have the form /documents/20117/<id>/<filename.ext>/<uuid>
    The last segment is a UUID with no extension — we want the segment
    that carries the actual filename and extension.
    """
    parsed = urlparse(url)
    parts = Path(parsed.path).parts
    # Walk backwards to find the first segment that has a known extension
    for part in reversed(parts):
        if re.search(r"\.(pdf|xlsx?|xls)$", part, re.IGNORECASE):
            name = re.sub(r"[^\w\-.]", "_", part)
            return name[:200] or "document"
    # Fallback: use last segment (UUID) — at least it's unique
    name = re.sub(r"[^\w\-.]", "_", parts[-1])
    return name[:200] or "document"


def _doc_type_from_url(url: str) -> DocType:
    """Detect doc type from URL — extension may appear mid-path before a UUID."""
    if re.search(r"\.(xlsx?|xls)\b", url, re.IGNORECASE):
        return DocType.EXCEL
    return DocType.PDF_TEXT
