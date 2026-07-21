from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
CANONICAL_DIR = DATA_DIR / "canonical"
VALUATION_DIR = DATA_DIR / "valuation"
RESEARCH_DIR = DATA_DIR / "research"
INDUSTRY_DIR = DATA_DIR / "industry"
INGESTION_DIR = DATA_DIR / "ingestion"
GENERATED_DIR = DATA_DIR / "generated"
PUBLIC_DIR = DATA_DIR / "public"
