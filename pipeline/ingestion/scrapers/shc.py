"""
SHC (Saudi Health Council) scraper.

shc.gov.sa is a SharePoint 2016 installation. Publications are not on a single
index page — the primary statistical output is the NCC (National Cancer Committee)
Annual Cancer Reports, exposed via a SharePoint REST API that returns JSON directly
(no JavaScript execution required).

Discovery strategy: SharePoint REST API
  URL: scrape_config["rest_api_url"]
  Response: {"d": {"results": [{"Title": "...", "File": {"ServerRelativeUrl": "/...pdf"}}]}}
  Full file URL = scrape_config["base_url"] + File.ServerRelativeUrl
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


DOWNLOAD_DIR = Path(__file__).parent.parent.parent / "downloads" / "shc"

REQUEST_DELAY = 0.5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SaudiHealthHub/1.0; "
        "research bot for open government data aggregation)"
    ),
    "Accept": "application/json;odata=verbose",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}

DOWNLOAD_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": "application/pdf,*/*;q=0.8",
}


class SHCScraper:
    def __init__(self, session: Session, source: DataSource):
        self.session = session
        self.source = source
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    def run(self) -> list[Document]:
        """
        Fetch the NCC Annual Cancer Reports via the SharePoint REST API
        and register new/updated documents.
        """
        rest_api_url: str = self.source.scrape_config.get("rest_api_url", "")
        base_url: str = self.source.scrape_config.get("base_url", self.source.base_url)

        if not rest_api_url:
            logger.warning("SHC: no rest_api_url in scrape_config — nothing to do")
            return []

        logger.info(f"Starting SHC scrape via SharePoint REST API")

        items = self._fetch_api_items(rest_api_url)
        logger.info(f"SHC REST API: {len(items)} items returned")

        new_or_updated: list[Document] = []
        with httpx.Client(headers=DOWNLOAD_HEADERS, follow_redirects=True, timeout=60) as client:
            for item in items:
                doc = self._process_item(client, item, base_url)
                if doc:
                    new_or_updated.append(doc)
                time.sleep(REQUEST_DELAY)

        self.session.flush()
        logger.info(f"SHC scrape complete. {len(new_or_updated)} new/updated documents.")
        return new_or_updated

    def _fetch_api_items(self, api_url: str) -> list[dict]:
        """
        Call the SharePoint REST API and return the list of items.
        Expected response shape: {"d": {"results": [...]}}
        """
        try:
            with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
                resp = client.get(api_url)
                resp.raise_for_status()
                data = resp.json()
            return data.get("d", {}).get("results", [])
        except Exception as e:
            logger.warning(f"SHC: REST API fetch failed ({api_url}): {e}")
            return []

    def _process_item(
        self, client: httpx.Client, item: dict, base_url: str
    ) -> Document | None:
        # Extract file URL from SharePoint REST response
        file_info = item.get("File") or {}
        server_relative_url = file_info.get("ServerRelativeUrl", "")
        if not server_relative_url:
            logger.debug(f"SHC: item has no File.ServerRelativeUrl: {item.get('Title')}")
            return None

        file_url = urljoin(base_url, server_relative_url)
        ext = Path(server_relative_url).suffix.lower()
        if ext not in (".pdf", ".xlsx", ".xls"):
            logger.debug(f"SHC: skipping non-document file: {file_url}")
            return None

        doc_type = DocType.EXCEL if ext in (".xlsx", ".xls") else DocType.PDF_TEXT

        raw_title = item.get("Title") or Path(server_relative_url).stem
        is_arabic = _is_arabic_text(raw_title)

        existing: Document | None = (
            self.session.query(Document).filter_by(original_url=file_url).first()
        )

        try:
            content, checksum = self._download(client, file_url)
        except Exception as e:
            logger.warning(f"SHC: failed to download {file_url}: {e}")
            return None

        if existing:
            if existing.checksum == checksum:
                logger.debug(f"SHC: unchanged: {file_url}")
                return None
            existing.checksum = checksum
            existing.ingest_status = IngestStatus.PENDING
            existing.last_fetched_at = datetime.now(timezone.utc)
            logger.info(f"SHC: updated: {file_url}")
            return existing

        filename = _safe_filename(file_url)
        file_path = DOWNLOAD_DIR / filename
        file_path.write_bytes(content)

        doc = Document(
            source_id=self.source.id,
            title_ar=raw_title if is_arabic else "",
            title_en=raw_title if not is_arabic else "",
            original_url=file_url,
            doc_type=doc_type,
            file_path=str(file_path),
            checksum=checksum,
            file_size_bytes=len(content),
            ingest_status=IngestStatus.PENDING,
            last_fetched_at=datetime.now(timezone.utc),
        )
        self.session.add(doc)
        logger.info(f"SHC: new document: {raw_title} [{file_url}]")
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
