"""
Seed the WEQAYA DataSource record.
Run from the project root (saudi-health-hub/):
  pipeline/.venv/Scripts/python.exe pipeline/seeds/seed_weqaya.py

WEQAYA (Saudi Center for Disease Prevention and Control) — weqaya.gov.sa
Publishes annual health status reports, weekly epidemiological bulletins,
and disease-specific surveillance reports.

Discovery strategy: HTML index pages (scrape_config["index_urls"])
  - /en/publications lists reports by category
  - Scraper extracts .pdf links from each index page
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
        # Annual health status / communicable disease reports
        "https://www.weqaya.gov.sa/en/publications",
        "https://www.weqaya.gov.sa/en/media/publications",
    ],
    "base_url": "https://www.weqaya.gov.sa",
    "file_types": ["pdf"],
}


def seed():
    init_db()
    with get_session() as session:
        existing = session.query(DataSource).filter_by(entity=EntityName.WEQAYA).first()
        if existing:
            existing.scrape_config = SCRAPE_CONFIG
            existing.base_url = "https://www.weqaya.gov.sa"
            existing.is_active = True
            print(f"Updated WEQAYA DataSource: {existing.id}")
            return

        source = DataSource(
            entity=EntityName.WEQAYA,
            name_ar="المركز الوطني للوقاية من الأمراض ومكافحتها",
            name_en="Saudi Center for Disease Prevention and Control",
            base_url="https://www.weqaya.gov.sa",
            scrape_config=SCRAPE_CONFIG,
            refresh_interval_hours=168,  # weekly
            is_active=True,
        )
        session.add(source)
        session.flush()
        print(f"Created WEQAYA DataSource: {source.id}")


if __name__ == "__main__":
    seed()
