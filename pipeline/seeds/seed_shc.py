"""
Seed the SHC DataSource record.
Run from the project root (saudi-health-hub/):
  pipeline/.venv/Scripts/python.exe pipeline/seeds/seed_shc.py

SHC (shc.gov.sa) is a SharePoint 2016 installation. Publications are not on a single
index page — the primary statistical output is the NCC Annual Cancer Reports, exposed
via a SharePoint REST API endpoint that returns JSON directly (no JS required).
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

from pipeline.catalog.database import init_db, get_session
from pipeline.catalog.models import DataSource, EntityName

SCRAPE_CONFIG = {
    # SharePoint REST API — returns JSON list of NCC Annual Cancer Report items.
    # Each item has a File.ServerRelativeUrl pointing to the PDF.
    # Endpoint documented at: shc.gov.sa/Arabic/NewNCC/Activities/_api/web/...
    "rest_api_url": (
        "https://shc.gov.sa/Arabic/NewNCC/Activities/_api/web/lists"
        "/getbytitle('AnnualReports')/items"
        "?$select=Title,FileType,IssueDate&$expand=File"
    ),
    "base_url": "https://shc.gov.sa",
    "file_types": ["pdf"],
}


def seed():
    init_db()
    with get_session() as session:
        existing = session.query(DataSource).filter_by(entity=EntityName.SHC).first()
        if existing:
            existing.scrape_config = SCRAPE_CONFIG
            existing.base_url = "https://shc.gov.sa"
            existing.is_active = True
            print(f"Updated SHC DataSource: {existing.id}")
            return

        source = DataSource(
            entity=EntityName.SHC,
            name_ar="المجلس الصحي السعودي",
            name_en="Saudi Health Council",
            base_url="https://shc.gov.sa",
            scrape_config=SCRAPE_CONFIG,
            refresh_interval_hours=168,
            is_active=True,
        )
        session.add(source)
        session.flush()
        print(f"Created SHC DataSource: {source.id}")


if __name__ == "__main__":
    seed()
