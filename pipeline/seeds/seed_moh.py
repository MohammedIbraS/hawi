"""
Seed the MOH DataSource record.
Run from the project root:
  pipeline/.venv/Scripts/python.exe pipeline/seeds/seed_moh.py
"""
import sys
import os

# Add project root (saudi-health-hub/) to path so `pipeline` package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

from pipeline.catalog.database import init_db, get_session
from pipeline.catalog.models import DataSource, EntityName


def seed():
    init_db()
    with get_session() as session:
        existing = session.query(DataSource).filter_by(entity=EntityName.MOH).first()
        if existing:
            print(f"MOH DataSource already exists: {existing.id}")
            return

        source = DataSource(
            entity=EntityName.MOH,
            name_ar="وزارة الصحة",
            name_en="Ministry of Health",
            base_url="https://www.moh.gov.sa",
            scrape_config={
                "stats_url": "https://www.moh.gov.sa/en/Ministry/Statistics/book/Pages/default.aspx",
                "file_types": ["pdf", "xlsx", "xls"],
            },
            refresh_interval_hours=24,
            is_active=True,
        )
        session.add(source)
        session.flush()
        print(f"Created MOH DataSource: {source.id}")


if __name__ == "__main__":
    seed()
