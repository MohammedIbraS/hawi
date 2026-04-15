"""
Seed the SCHS DataSource record.
Run from the project root (saudi-health-hub/):
  pipeline/.venv/Scripts/python.exe pipeline/seeds/seed_schs.py

NOTE: The domain schs.gov.sa does not resolve (NXDOMAIN as of 2026-03).
The Saudi Center for Health Statistics function appears to have been absorbed
into the Ministry of Health. MOH yearbooks are already ingested via the MOH
scraper. SCHS is seeded as inactive until a valid source URL is identified.
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
        existing = session.query(DataSource).filter_by(entity=EntityName.SCHS).first()
        if existing:
            existing.is_active = False
            existing.scrape_config = {
                "note": "Domain schs.gov.sa does not resolve. Function absorbed into MOH. Disabled until valid URL found.",
                "index_urls": [],
            }
            print(f"Updated SCHS DataSource (marked inactive): {existing.id}")
            return

        source = DataSource(
            entity=EntityName.SCHS,
            name_ar="مركز الإحصاءات الصحية السعودي",
            name_en="Saudi Center for Health Statistics",
            base_url="https://www.schs.gov.sa",
            scrape_config={
                "note": "Domain schs.gov.sa does not resolve. Function absorbed into MOH. Disabled until valid URL found.",
                "index_urls": [],
            },
            refresh_interval_hours=168,
            is_active=False,
        )
        session.add(source)
        session.flush()
        print(f"Created SCHS DataSource (inactive): {source.id}")


if __name__ == "__main__":
    seed()
