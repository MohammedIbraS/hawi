"""
Seed the SFDA DataSource record.
Run from the project root (saudi-health-hub/):
  pipeline/.venv/Scripts/python.exe pipeline/seeds/seed_sfda.py

SFDA (sfda.gov.sa) is a Drupal site. Annual reports are on a single HTML page
with direct PDF links — no JavaScript required, no pagination.
The /en/statistics page only has one stale 2013 PDF and should be avoided.
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
        # Annual reports 2017–2024 — direct PDF links, no JS needed
        "https://www.sfda.gov.sa/en/annual-report",
    ],
    "paginated_urls": [
        # Regulatory reports: ADE reports, inspection stats, GCP/GMP trends, etc.
        # Drupal view paginated with ?page=N (9 items/page, iterate until empty)
        "https://www.sfda.gov.sa/en/information_list",
    ],
    "file_types": ["pdf", "xlsx", "xls"],
}


def seed():
    init_db()
    with get_session() as session:
        existing = session.query(DataSource).filter_by(entity=EntityName.SFDA).first()
        if existing:
            existing.scrape_config = SCRAPE_CONFIG
            existing.is_active = True
            print(f"Updated SFDA DataSource: {existing.id}")
            return

        source = DataSource(
            entity=EntityName.SFDA,
            name_ar="هيئة الغذاء والدواء",
            name_en="Saudi Food and Drug Authority",
            base_url="https://www.sfda.gov.sa",
            scrape_config=SCRAPE_CONFIG,
            refresh_interval_hours=168,
            is_active=True,
        )
        session.add(source)
        session.flush()
        print(f"Created SFDA DataSource: {source.id}")


if __name__ == "__main__":
    seed()
