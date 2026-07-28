import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.theme_sector_inference import (  # noqa: E402
    build_theme_sector_inference,
    write_theme_sector_inference,
)


def main() -> None:
    report = build_theme_sector_inference(ROOT)
    write_theme_sector_inference(
        report,
        ROOT / "data/generated/theme_sector_inference/theme_sector_inference.json",
    )
    print(report["summary"])


if __name__ == "__main__":
    main()
