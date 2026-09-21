"""법령 snapshot 저장소.

AP-07/BR-006: 분석 당시 근거를 보존해 과거 결과를 재현한다.
ER-001: 법제처 API 장애 시 '검증된 snapshot'을 대체 근거로 쓸 수 있게 한다.

W1에서는 파일 기반 구현을 쓰고, W3(Supabase)에서 동일한 프로토콜로 DB 구현을 끼운다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from app.adapters.law.models import LawSnapshot


class SnapshotStore(Protocol):
    """W3에서 Postgres 구현으로 교체될 인터페이스 (NFR-011)."""

    def save(self, snapshot: LawSnapshot) -> str: ...
    def get(self, law_id: str) -> LawSnapshot | None: ...
    def exists(self, law_id: str) -> bool: ...


class FileSnapshotStore:
    """law_id 기준 JSON 파일 저장. 로컬 개발/평가용."""

    def __init__(self, root: str | Path = ".snapshots"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, law_id: str) -> Path:
        safe = "".join(c for c in law_id if c.isalnum() or c in "-_")
        return self.root / f"{safe}.json"

    def save(self, snapshot: LawSnapshot) -> str:
        path = self._path(snapshot.law_id)
        path.write_text(
            snapshot.model_dump_json(indent=2, exclude_none=False), encoding="utf-8"
        )
        return str(path)

    def get(self, law_id: str) -> LawSnapshot | None:
        path = self._path(law_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        snapshot = LawSnapshot.model_validate(data)
        # 원천이 cache임을 명시해야 UI가 '기준일/캐시 상태'를 표시할 수 있다 (ER-001).
        return snapshot.model_copy(update={"source": "cache"})

    def exists(self, law_id: str) -> bool:
        return self._path(law_id).exists()

    def all_ids(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json"))
