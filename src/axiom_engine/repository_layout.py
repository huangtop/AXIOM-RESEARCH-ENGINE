from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CanonicalRepositoryLayout:
    """Filesystem contract for canonical AXIOM repositories.

    ``root`` may be the canonical data root (containing ``universe/``) or a
    Universe directory. Both forms remain
    readable so migrations can be staged and rolled back safely.
    """

    root: Path
    universe_dir: Path
    legacy: bool = False

    @classmethod
    def resolve(cls, path: str | Path) -> "CanonicalRepositoryLayout":
        candidate = Path(path)
        if (candidate / "universe").is_dir():
            return cls(
                root=candidate,
                universe_dir=candidate / "universe",
                legacy=False,
            )

        return cls(
            root=candidate.parent,
            universe_dir=candidate,
            legacy=True,
        )

    @property
    def companies_path(self) -> Path:
        return self.universe_dir / "companies.json"

    @property
    def securities_path(self) -> Path:
        return self.universe_dir / "securities.json"
