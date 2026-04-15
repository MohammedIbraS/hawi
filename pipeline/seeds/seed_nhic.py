"""
Seed the NHIC DataSource record.
Run from the project root (saudi-health-hub/):
  pipeline/.venv/Scripts/python.exe pipeline/seeds/seed_nhic.py

NHIC (nhic.gov.sa) is a JavaScript SPA — PDF URLs are hardcoded in the JS bundle
and cannot be discovered via HTML scraping. Known document URLs are seeded directly
in scrape_config["direct_urls"] and updated here whenever new reports are published.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

from pipeline.catalog.database import init_db, get_session
from pipeline.catalog.models import DataSource, EntityName

SCRAPE_CONFIG = {
    # NHIC is a JS SPA — no crawlable index page exists.
    # PDFs are listed in the /Reports route but rendered entirely by JavaScript.
    # Known report URLs are listed here and downloaded directly by the scraper.
    "direct_urls": [
        "https://nhic.gov.sa/standards/Reports/KSA%20HA%202019_2021REPORT_ApprovedByCouncil_1.6-.pdf",
        "https://nhic.gov.sa/standards/Reports/National%20Health%20Accounts-%202022-2023.pdf",
    ],
    "file_types": ["pdf"],
}


def seed():
    init_db()
    with get_session() as session:
        existing = session.query(DataSource).filter_by(entity=EntityName.NHIC).first()
        if existing:
            existing.scrape_config = SCRAPE_CONFIG
            existing.base_url = "https://nhic.gov.sa"
            existing.is_active = True
            print(f"Updated NHIC DataSource: {existing.id}")
            return

        source = DataSource(
            entity=EntityName.NHIC,
            name_ar="المركز الوطني للمعلومات الصحية",
            name_en="National Health Information Center",
            base_url="https://nhic.gov.sa",
            scrape_config=SCRAPE_CONFIG,
            refresh_interval_hours=168,
            is_active=True,
        )
        session.add(source)
        session.flush()
        print(f"Created NHIC DataSource: {source.id}")


if __name__ == "__main__":
    seed()
