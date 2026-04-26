"""
SFDA (Saudi Food and Drug Authority) scraper.

sfda.gov.sa is a Drupal site. Two discovery strategies:

1. index_urls — single HTML pages with direct PDF/Excel links (annual reports).
2. paginated_urls — Drupal views with ?page=N pagination (information_list):
   https://www.sfda.gov.sa/en/information_list
   Each page has 9 items; iterate until a page returns no document links.
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

from pipeline.catalog.models import DataSource, Document, DocType, IngestStatus
from pipeline.ingestion.scrapers._utils import http_get_with_retry


DOWNLOAD_DIR = Path(__file__).parent.parent.parent / "downloads" / "sfda"

SFDA_BASE_URL = "https://www.sfda.gov.sa"

REQUEST_DELAY = 0.5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SaudiHealthHub/1.0; "
        "research bot for open government data aggregation)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}


class SFDAScraper:
    def __init__(self, session: Session, source: DataSource):
        self.session = session
        self.source = source
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    def run(self) -> list[Document]:
        """
        Scrape SFDA index pages and register new/updated documents.
        Returns list of Document records created or marked for re-ingestion.
        """
        index_urls: list[str] = self.source.scrape_config.get("index_urls", [])
        paginated_urls: list[str] = self.source.scrape_config.get("paginated_urls", [])

        if not index_urls and not paginated_urls:
            logger.warning("SFDA: no index_urls or paginated_urls in scrape_config — nothing to do")
            return []

        logger.info(f"Starting SFDA scrape ({len(index_urls)} index, {len(paginated_urls)} paginated)")

        seen: set[str] = set()
        all_links: list[dict] = []

        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
            for url in index_urls:
                links = self._fetch_document_links(client, url)
                logger.info(f"SFDA index {url}: found {len(links)} document links")
                for link in links:
                    if link["url"] not in seen:
                        seen.add(link["url"])
                        all_links.append(link)
                time.sleep(REQUEST_DELAY)

            for base_url in paginated_urls:
                links = self._fetch_paginated_links(client, base_url)
                logger.info(f"SFDA paginated {base_url}: found {len(links)} document links")
                for link in links:
                    if link["url"] not in seen:
                        seen.add(link["url"])
                        all_links.append(link)

        logger.info(f"SFDA: {len(all_links)} unique document links total")

        new_or_updated: list[Document] = []
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=60) as client:
            for link_info in all_links:
                doc = self._process_link(client, link_info)
                if doc:
                    new_or_updated.append(doc)
                time.sleep(REQUEST_DELAY)

        self.session.flush()
        logger.info(f"SFDA scrape complete. {len(new_or_updated)} new/updated documents.")
        return new_or_updated

    def _fetch_paginated_links(self, client: httpx.Client, base_url: str) -> list[dict]:
        """Paginate through a Drupal view (?page=N) and collect all document links."""
        all_links: list[dict] = []
        page = 0
        while True:
            url = f"{base_url}?page={page}"
            try:
                response = client.get(url)
                response.raise_for_status()
                html = response.text
            except httpx.HTTPError as e:
                logger.warning(f"SFDA: HTTP error fetching {url}: {e}")
                break

            links = self._parse_information_list(html)
            if not links:
                break
            all_links.extend(links)
            logger.debug(f"SFDA info_list page={page}: {len(links)} items")

            # Stop if there's no "next page" link in pagination
            if f"page={page + 1}" not in html:
                break
            page += 1
            time.sleep(REQUEST_DELAY)

        return all_links

    def _parse_information_list(self, html: str) -> list[dict]:
        """Parse document items from the information_list Drupal view HTML."""
        import html as html_module
        links = []

        # Each item: date span, category span, anchor with /sites/default/files/ href
        item_pattern = re.compile(
            r'<span[^>]*class="[^"]*date[^"]*"[^>]*>([^<]+)</span>'
            r'.*?'
            r'<a\s+href="(/sites/default/files/[^"]+\.(pdf|xlsx?|xls))"[^>]*>([^<]+)</a>',
            re.IGNORECASE | re.DOTALL,
        )

        for m in item_pattern.finditer(html):
            date_str = m.group(1).strip()
            href = m.group(2)
            ext = m.group(3).lower()
            title_raw = html_module.unescape(m.group(4).strip())

            file_url = urljoin(SFDA_BASE_URL, href)
            doc_type = DocType.EXCEL if ext in ("xlsx", "xls") else DocType.PDF_TEXT

            # Parse publication year from the date string (YYYY-MM-DD or YYYY)
            year_m = re.search(r"(20\d{2})", date_str)
            pub_year = year_m.group(1) if year_m else ""

            title_en = title_raw or (f"SFDA Information {pub_year}".strip())

            links.append({
                "url": file_url,
                "title_en": title_en,
                "title_ar": "",
                "doc_type": doc_type,
                "publication_date": date_str if re.match(r"\d{4}-\d{2}-\d{2}", date_str) else None,
            })

        return links

    def _fetch_document_links(self, client: httpx.Client, index_url: str) -> list[dict]:
        links = []
        try:
            response = client.get(index_url)
            response.raise_for_status()
            html = response.text
        except httpx.HTTPError as e:
            logger.warning(f"SFDA: HTTP error fetching index {index_url}: {e}")
            return links

        href_pattern = re.compile(
            r'href=["\']([^"\']*\.(?:pdf|xlsx?|xls))["\']',
            re.IGNORECASE,
        )

        for match in href_pattern.finditer(html):
            href = match.group(1)
            url = urljoin(SFDA_BASE_URL, href) if not href.startswith("http") else href
            ext = Path(href).suffix.lower().lstrip(".")
            doc_type = DocType.EXCEL if ext in ("xlsx", "xls") else DocType.PDF_TEXT

            # Try anchor text first; fall back to deriving title from the filename
            start = max(0, match.start() - 300)
            context = html[start : match.end() + 100]
            anchor = _extract_anchor_text(context, match.start() - start)
            title_en, title_ar = _sfda_title_from_url(url, anchor)

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
            logger.warning(f"SFDA: failed to download {url}: {e}")
            return None

        if existing:
            if existing.checksum == checksum:
                logger.debug(f"SFDA: unchanged: {url}")
                return None
            existing.checksum = checksum
            existing.ingest_status = IngestStatus.PENDING
            existing.last_fetched_at = datetime.now(timezone.utc)
            logger.info(f"SFDA: updated: {url}")
            return existing

        filename = _safe_filename(url)
        file_path = DOWNLOAD_DIR / filename
        file_path.write_bytes(content)

        pub_date = None
        raw_date = link_info.get("publication_date")
        if raw_date:
            try:
                from datetime import date
                pub_date = date.fromisoformat(raw_date)
            except ValueError:
                pass

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
            publication_date=pub_date,
        )
        self.session.add(doc)
        logger.info(f"SFDA: new document: {link_info.get('title_en') or link_info.get('title_ar') or url}")
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


def _sfda_title_from_url(url: str, anchor: str) -> tuple[str, str]:
    """
    Return (title_en, title_ar) for an SFDA document URL.

    Priority:
    1. If anchor text is specific enough (contains a year or Arabic), use it.
    2. Extract year from URL filename and build "SFDA Annual Report {year}".
    3. Fall back to anchor or generic title.
    """
    from urllib.parse import unquote

    # If anchor is informative, use it
    if anchor:
        if _is_arabic_text(anchor):
            year_match = re.search(r"(20\d{2})", anchor)
            year = year_match.group(1) if year_match else ""
            title_ar = anchor
            title_en = f"SFDA Annual Report {year}".strip() if year else "SFDA Annual Report"
            return title_en, title_ar
        if re.search(r"20\d{2}", anchor) and len(anchor) > 5:
            return anchor, ""

    # Parse year from filename
    parsed_path = unquote(urlparse(url).path)
    filename = Path(parsed_path).stem  # e.g. "NEW 2024 _0", "2023_1", "20172025"

    # Strategy 2019-2025 style: 8-digit run like "20172025"
    range_match = re.match(r"^(20\d{2})(20\d{2})$", filename.strip())
    if range_match:
        y1, y2 = range_match.group(1), range_match.group(2)
        return f"SFDA Strategy {y1}–{y2}", ""

    # Single year anywhere in filename
    year_match = re.search(r"(20\d{2})", filename)
    if year_match:
        year = year_match.group(1)
        # Check if Arabic characters are in the anchor → bilingual
        if anchor and _is_arabic_text(anchor):
            return f"SFDA Annual Report {year}", anchor
        return f"SFDA Annual Report {year}", ""

    # Fall back to anchor or generic
    if anchor and not _is_arabic_text(anchor):
        return anchor, ""
    return "SFDA Annual Report", anchor if anchor else ""


def _is_arabic_text(text: str) -> bool:
    arabic_chars = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
    return arabic_chars / max(len(text), 1) > 0.3


def _safe_filename(url: str) -> str:
    from urllib.parse import unquote
    parsed = urlparse(url)
    parts = Path(parsed.path).parts
    for part in reversed(parts):
        if re.search(r"\.(pdf|xlsx?|xls)$", part, re.IGNORECASE):
            name = re.sub(r"[^\w\-.]", "_", unquote(part))
            return name[:200] or "document"
    name = re.sub(r"[^\w\-.]", "_", parts[-1]) if parts else "document"
    return name[:200] or "document"
