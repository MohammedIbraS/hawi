"""
WEQAYA (Saudi Center for Disease Prevention and Control) scraper.

weqaya.gov.sa — server-side rendered government portal.

Discovery strategy: HTML index pages (scrape_config["index_urls"])
  - Fetches each index URL and extracts all .pdf href links via regex.
  - Falls back to scrape_config["direct_urls"] if index pages yield nothing.

Primary publications:
  - Annual health status reports (التقرير السنوي)
  - Weekly epidemiological bulletins (النشرة الوبائية الأسبوعية)
  - Disease-specific surveillance reports (MERS, dengue, etc.)
"""
import hashlib
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
from datetime import datetime, timezone

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from pipeline.catalog.models import DataSource, Document, DocType, IngestStatus
from pipeline.ingestion.scrapers._utils import http_get_with_retry


DOWNLOAD_DIR = Path(__file__).parent.parent.parent / "downloads" / "weqaya"

REQUEST_DELAY = 1.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SaudiHealthHub/1.0; "
        "research bot for open government data aggregation)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ar,en;q=0.9",
}

# Match href="...pdf" attributes
_HREF_PDF_RE = re.compile(r'href=["\']([^"\']*\.pdf)["\']', re.IGNORECASE)

# Only keep PDFs with at least one of these keywords (case-insensitive)
_RELEVANT_RE = re.compile(
    r"report|annual|health|bulletin|epidemi|surveillance|disease|mers|dengue|saudi"
    r"|تقرير|صحة|وبائي|مرض|رصد|سنوي",
    re.IGNORECASE,
)

# Extract link text near an href (up to 200 chars before the href)
_LINK_TEXT_RE = re.compile(r">([^<]{3,150})</a>", re.IGNORECASE)

WEQAYA_DOMAINS = {"weqaya.gov.sa", "www.weqaya.gov.sa"}


class WEQAYAScraper:
    def __init__(self, session: Session, source: DataSource):
        self.session = session
        self.source = source
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    def run(self) -> list[Document]:
        config = self.source.scrape_config or {}
        base_url: str = config.get("base_url", "https://www.weqaya.gov.sa")
        index_urls: list[str] = config.get("index_urls", [])
        direct_urls: list[str] = config.get("direct_urls", [])

        seen: set[str] = set()
        all_links: list[dict] = []

        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
            for url in index_urls:
                try:
                    links = self._fetch_document_links(client, url, base_url)
                    logger.info(f"WEQAYA index {url}: found {len(links)} PDF link(s)")
                    for link in links:
                        if link["url"] not in seen:
                            seen.add(link["url"])
                            all_links.append(link)
                except Exception as e:
                    logger.warning(f"WEQAYA: failed to fetch index {url}: {e}")
                time.sleep(REQUEST_DELAY)

        for url in direct_urls:
            if url not in seen:
                seen.add(url)
                name = unquote(Path(url).stem).replace("_", " ").replace("-", " ").strip()
                all_links.append({"url": url, "title": name})

        if not all_links:
            logger.warning("WEQAYA: no document links found — check index_urls or add direct_urls")
            return []

        logger.info(f"WEQAYA: {len(all_links)} unique document link(s) to process")

        new_or_updated: list[Document] = []
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=60) as client:
            for link_info in all_links:
                doc = self._process_link(client, link_info)
                if doc:
                    new_or_updated.append(doc)
                time.sleep(REQUEST_DELAY)

        self.session.flush()
        logger.info(f"WEQAYA scrape complete. {len(new_or_updated)} new/updated document(s).")
        return new_or_updated

    def _fetch_document_links(
        self, client: httpx.Client, index_url: str, base_url: str
    ) -> list[dict]:
        resp = http_get_with_retry(client, index_url)
        resp.raise_for_status()
        html = resp.text

        links: list[dict] = []
        for match in _HREF_PDF_RE.finditer(html):
            href = match.group(1)
            full_url = urljoin(base_url, href) if not href.startswith("http") else href

            # Validate domain
            netloc = urlparse(full_url).netloc
            if netloc not in WEQAYA_DOMAINS and not netloc.endswith(".weqaya.gov.sa"):
                continue

            # Extract link text from surrounding HTML context (200 chars after the href)
            pos = match.end()
            context_after = html[pos : pos + 300]
            text_match = _LINK_TEXT_RE.search(context_after)
            raw_name = unquote(Path(full_url).stem)
            title = (
                text_match.group(1).strip()
                if text_match and 3 <= len(text_match.group(1).strip()) <= 200
                else raw_name.replace("_", " ").replace("-", " ").strip()
            )

            # Filter to relevant documents only
            if not _RELEVANT_RE.search(title) and not _RELEVANT_RE.search(raw_name):
                continue

            links.append({"url": full_url, "title": title})

        return links

    def _process_link(self, client: httpx.Client, link_info: dict) -> Document | None:
        url: str = link_info["url"]
        title: str = link_info.get("title", "")

        existing: Document | None = (
            self.session.query(Document).filter_by(original_url=url).first()
        )

        try:
            content, checksum = self._download(client, url)
        except Exception as e:
            logger.warning(f"WEQAYA: failed to download {url}: {e}")
            return None

        if existing:
            if existing.checksum == checksum:
                logger.debug(f"WEQAYA: unchanged: {url}")
                return None
            existing.checksum = checksum
            existing.ingest_status = IngestStatus.PENDING
            existing.last_fetched_at = datetime.now(timezone.utc)
            logger.info(f"WEQAYA: updated: {url}")
            return existing

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
        logger.info(f"WEQAYA: new document: {title[:80]} [{url}]")
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
    name = unquote(Path(url).name)
    name = re.sub(r"[^\w\-.]", "_", name)
    return name[:200] or "document"
