from pathlib import Path
import tomllib


def test_yahoo_runtime_dependency_is_declared() -> None:
    payload = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = payload["project"]["optional-dependencies"]["yahoo"]
    assert any(item.startswith("yfinance>=") for item in deps)
