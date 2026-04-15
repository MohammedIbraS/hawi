"""
Run all seeds in order.
  python seeds/seed_all.py
"""
from pipeline.seeds.seed_moh import seed as seed_moh
from pipeline.seeds.seed_gastat import seed as seed_gastat
from pipeline.seeds.seed_nhic import seed as seed_nhic
from pipeline.seeds.seed_shc import seed as seed_shc
from pipeline.seeds.seed_sfda import seed as seed_sfda
from pipeline.seeds.seed_schs import seed as seed_schs
from pipeline.seeds.seed_cchi import seed as seed_cchi
from pipeline.seeds.seed_weqaya import seed as seed_weqaya

if __name__ == "__main__":
    print("=== Seeding MOH ===")
    seed_moh()

    print("\n=== Seeding GASTAT ===")
    seed_gastat()

    print("\n=== Seeding NHIC ===")
    seed_nhic()

    print("\n=== Seeding SHC ===")
    seed_shc()

    print("\n=== Seeding SFDA ===")
    seed_sfda()

    print("\n=== Seeding SCHS ===")
    seed_schs()

    print("\n=== Seeding CCHI ===")
    seed_cchi()

    print("\n=== Seeding WEQAYA ===")
    seed_weqaya()

    print("\nAll seeds complete.")
