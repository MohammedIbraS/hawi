"""
CCHI / CHI (Council of Health Insurance) scraper.

www.cchi.gov.sa permanently redirects to www.chi.gov.sa (rebranded name).
The site is SharePoint 2019 on-premises, fully server-side rendered —
no JavaScript execution required, no pagination.

Discovery strategy: HTML index pages (scrape_config["index_urls"])
  Annual Reports:    https://www.chi.gov.sa/en/MediaCenter/pages/annual-reports.aspx
  Research Library:  https://www.chi.gov.sa/en/knowledge-center/Pages/research-library.aspx
  Awareness Manuals: https://www.chi.gov.sa/en/knowledge-center/Pages/awareness-manuals.aspx
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


DOWNLOAD_DIR = Path(__file__).parent.parent.parent / "downloads" / "cchi"

CHI_BASE_URL = "https://www.chi.gov.sa"

REQUEST_DELAY = 0.5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SaudiHealthHub/1.0; "
        "research bot for open government data aggregation)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}


class CCHIScraper:
    def __init__(self, session: Session, source: DataSource):
        self.session = session
        self.source = source
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    def run(self) -> list[Document]:
        """
        Scrape CHI index pages and register new/updated documents.
        Returns list of Document records created or marked for re-ingestion.
        """
        index_urls: list[str] = self.source.scrape_config.get("index_urls", [])
        if not index_urls:
            logger.warning("CCHI: no index_urls in scrape_config — nothing to do")
            return []

        logger.info(f"Starting CCHI scrape ({len(index_urls)} index page(s))")

        seen: set[str] = set()
        all_links: list[dict] = []

        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
            for url in index_urls:
                links = self._fetch_document_links(client, url)
                logger.info(f"CCHI index {url}: found {len(links)} document links")
                for link in links:
                    if link["url"] not in seen:
                        seen.add(link["url"])
                        all_links.append(link)
                time.sleep(REQUEST_DELAY)

        logger.info(f"CCHI: {len(all_links)} unique document links total")

        new_or_updated: list[Document] = []
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=60) as client:
            for link_info in all_links:
                doc = self._process_link(client, link_info)
                if doc:
                    new_or_updated.append(doc)
                time.sleep(REQUEST_DELAY)

        self.session.flush()
        logger.info(f"CCHI scrape complete. {len(new_or_updated)} new/updated documents.")
        return new_or_updated

    def _fetch_document_links(self, client: httpx.Client, index_url: str) -> list[dict]:
        links = []
        try:
            response = client.get(index_url)
            response.raise_for_status()
            html = response.text
        except httpx.HTTPError as e:
            logger.warning(f"CCHI: HTTP error fetching index {index_url}: {e}")
            return links

        href_pattern = re.compile(
            r'href=["\']([^"\']*\.(?:pdf|xlsx?|xls))["\']',
            re.IGNORECASE,
        )

        for match in href_pattern.finditer(html):
            href = match.group(1)
            url = urljoin(CHI_BASE_URL, href) if not href.startswith("http") else href

            # Skip URLs from other domains (e.g. external links)
            if urlparse(url).netloc not in ("www.chi.gov.sa", "chi.gov.sa"):
                continue

            ext = Path(unquote(urlparse(url).path)).suffix.lower().lstrip(".")
            doc_type = DocType.EXCEL if ext in ("xlsx", "xls") else DocType.PDF_TEXT

            # Derive title from surrounding anchor text or URL filename
            start = max(0, match.start() - 300)
            context = html[start: match.end() + 100]
            anchor = _extract_anchor_text(context, match.start() - start)
            title_en, title_ar = _chi_title(url, anchor)

            links.append({
                "url": url,
                "title_ar": title_ar,
                "title_en": title_en,
                "doc_type": doc_type,
            })

        return links

    def _process_link(self, client: httpx.Client, link_info: dict) -> Document | None:
        url = link_info["url"]

        existing: Document | None = (
            self.session.query(Document).filter_by(original_url=url).first()
        )

        try:
            content, checksum = self._download(client, url)
        except Exception as e:
            logger.warning(f"CCHI: failed to download {url}: {e}")
            return None

        if existing:
            if existing.checksum == checksum:
                logger.debug(f"CCHI: unchanged: {url}")
                return None
            existing.checksum = checksum
            existing.ingest_status = IngestStatus.PENDING
            existing.last_fetched_at = datetime.now(timezone.utc)
            logger.info(f"CCHI: updated: {url}")
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
        logger.info(f"CCHI: new document: {link_info.get('title_en') or link_info.get('title_ar') or url}")
        return doc

    def _download(self, client: httpx.Client, url: str) -> tuple[bytes, str]:
        response = http_get_with_retry(client, url)
        response.raise_for_status()
        content = response.content
        checksum = hashlib.sha256(content).hexdigest()
        return content, checksum


def _extract_anchor_text(context: str, link_pos: int) -> str:
    match = re.search(r">([^<]{5,120})</a>", context[:link_pos])
    if match:
        return match.group(1).strip()
    match = re.search(r">([^<]{5,120})</a>", context[link_pos:])
    if match:
        return match.group(1).strip()
    return ""


def _chi_title(url: str, anchor: str) -> tuple[str, str]:
    """Return (title_en, title_ar) for a CHI document URL.

    Always derive the title from the URL filename — the anchor text in the
    CHI HTML is often wrong (nearby entries bleed into the context window).
    The URL filename is authoritative: 'Annual Report 2023.pdf' → 'Annual Report 2023'.
    """
    # URL filename is authoritative
    filename = unquote(Path(urlparse(url).path).stem)
    filename = re.sub(r"\s+", " ", filename).strip()
    if filename:
        return filename, ""

    # Fall back to anchor only if filename is empty
    if anchor and _is_arabic_text(anchor):
        return "", anchor
    if anchor:
        return anchor, ""

    return "CHI Document", ""


def _is_arabic_text(text: str) -> bool:
    arabic_chars = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
    return arabic_chars / max(len(text), 1) > 0.3


def _safe_filename(url: str) -> str:
    parsed = urlparse(url)
    parts = Path(unquote(parsed.path)).parts
    for part in reversed(parts):
        if re.search(r"\.(pdf|xlsx?|xls)$", part, re.IGNORECASE):
            name = re.sub(r"[^\w\-.]", "_", part)
            return name[:200] or "document"
    name = re.sub(r"[^\w\-.]", "_", parts[-1]) if parts else "document"
    return name[:200] or "document"
