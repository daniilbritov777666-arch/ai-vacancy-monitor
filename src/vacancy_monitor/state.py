from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SeenState:
    seen_ids: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path) -> "SeenState":
        if not path.exists():
            return cls()

        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(set(data.get("seen_ids", [])))

    def contains(self, post_id: str) -> bool:
        return post_id in self.seen_ids

    def add(self, post_id: str) -> None:
        self.seen_ids.add(post_id)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"seen_ids": sorted(self.seen_ids)}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
