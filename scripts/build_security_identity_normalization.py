#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.security_identity import (  # noqa: E402
    build_security_identity_normalization,
    write_security_identity_normalization,
)


def main() -> None:
    report = build_security_identity_normalization(ROOT)
    write_security_identity_normalization(
        report, ROOT / "data/generated/security_identity/security_identity_normalization.json"
    )
    print(report["summary"])


if __name__ == "__main__":
    main()
