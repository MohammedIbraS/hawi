"""
Seed the CCHI / CHI DataSource record.
Run from the project root (saudi-health-hub/):
  pipeline/.venv/Scripts/python.exe pipeline/seeds/seed_cchi.py

CCHI (Council of Health Insurance) rebranded to CHI.
www.cchi.gov.sa → redirects to www.chi.gov.sa
SharePoint 2019 on-premises, server-side rendered — no JS required.

Index pages:
  - Annual Reports (17 PDFs, 2007–2024)
  - Research Library (8 white papers / research reports)
  - Awareness Manuals (7 PDFs)
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

from pipeline.catalog.database import init_db, get_session
from pipeline.catalog.models import DataSource, EntityName

SCRAPE_CONFIG = {
    "index_urls": [
        # 17 annual reports (2007–2024) — direct PDF links in HTML
        "https://www.chi.gov.sa/en/MediaCenter/pages/annual-reports.aspx",
        # 8 research white papers
        "https://www.chi.gov.sa/en/knowledge-center/Pages/research-library.aspx",
        # 7 awareness/insurance manuals
        "https://www.chi.gov.sa/en/knowledge-center/Pages/awareness-manuals.aspx",
    ],
    "base_url": "https://www.chi.gov.sa",
    "file_types": ["pdf", "xlsx", "xls"],
}


def seed():
    init_db()
    with get_session() as session:
        existing = session.query(DataSource).filter_by(entity=EntityName.CCHI).first()
        if existing:
            existing.scrape_config = SCRAPE_CONFIG
            existing.is_active = True
            print(f"Updated CCHI DataSource: {existing.id}")
            return

        source = DataSource(
            entity=EntityName.CCHI,
            name_ar="مجلس الضمان الصحي",
            name_en="Council of Health Insurance",
            base_url="https://www.chi.gov.sa",
            scrape_config=SCRAPE_CONFIG,
            refresh_interval_hours=168,  # weekly
            is_active=True,
        )
        session.add(source)
        session.flush()
        print(f"Created CCHI DataSource: {source.id}")


if __name__ == "__main__":
    seed()
