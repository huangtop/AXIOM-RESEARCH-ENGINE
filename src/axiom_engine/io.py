from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter

T = TypeVar("T", bound=BaseModel)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json", exclude_none=True)
    elif isinstance(payload, list):
        payload = [
            item.model_dump(mode="json", exclude_none=True) if isinstance(item, BaseModel) else item
            for item in payload
        ]
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def load_models(path: Path, model_type: type[T]) -> list[T]:
    adapter = TypeAdapter(list[model_type])
    return adapter.validate_python(read_json(path))
