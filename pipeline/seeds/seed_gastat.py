"""
Seed the GASTAT DataSource record.
Run from the project root (saudi-health-hub/):
  pipeline/.venv/Scripts/python.exe pipeline/seeds/seed_gastat.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

from pipeline.catalog.database import init_db, get_session
from pipeline.catalog.models import DataSource, EntityName


def seed():
    init_db()
    with get_session() as session:
        existing = session.query(DataSource).filter_by(entity=EntityName.GASTAT).first()
        if existing:
            print(f"GASTAT DataSource already exists: {existing.id}")
            return

        source = DataSource(
            entity=EntityName.GASTAT,
            name_ar="الهيئة العامة للإحصاء",
            name_en="General Authority for Statistics",
            base_url="https://www.stats.gov.sa",
            scrape_config={
                "search_url": "https://www.stats.gov.sa/en/search",
                "search_queries": ["health", "healthcare", "hospital", "mortality", "disease"],
                "filter": "publications",
                "file_types": ["pdf", "xlsx", "xls"],
                "page_size": 10,
            },
            refresh_interval_hours=48,
            is_active=True,
        )
        session.add(source)
        session.flush()
        print(f"Created GASTAT DataSource: {source.id}")


if __name__ == "__main__":
    seed()
