"""사내 규정 도메인 (문서 12 §4).

사내 규정의 식별자·조문번호·원문은 **사실**이다. 법령과 같은 원칙으로 다룬다(BR-001, AP-05):
코드가 규정집에서 공급하고, LLM은 후보 번호([P1]…)와 원문 인용으로만 가리킨다.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

CORPUS_DIR = Path(__file__).parent / "corpus"


class PolicyArticle(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_id: str
    policy_title: str
    owner_dept: str
    version: str
    article_no: str
    title: str
    text: str = Field(..., description="사내 규정 조문 원문. 인용 검증의 기준 문자열")

    @property
    def ref(self) -> str:
        return f"{self.policy_id} {self.article_no}"

    def render(self, label: str) -> str:
        return (
            f"[{label}] {self.policy_title} {self.article_no}({self.title})"
            f" · 소관 {self.owner_dept}\n"
            f"원문: {self.text}"
        )


class PolicyCorpus(BaseModel):
    model_config = ConfigDict(frozen=True)

    company_id: str
    company_name: str
    label: str
    profile: dict
    articles: list[PolicyArticle]

    @classmethod
    def load(cls, company_id: str = "virtual-card-co", root: Path = CORPUS_DIR) -> PolicyCorpus:
        path = root / f"{company_id.replace('-', '_')}.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        arts = [
            PolicyArticle(
                policy_id=p["policy_id"],
                policy_title=p["title"],
                owner_dept=p["owner_dept"],
                version=p["version"],
                article_no=a["article_no"],
                title=a["title"],
                text=a["text"],
            )
            for p in raw["policies"]
            for a in p["articles"]
        ]
        refs = [a.ref for a in arts]
        if len(refs) != len(set(refs)):
            raise ValueError("사내 규정 조문 식별자(규정 ID + 조문번호)가 중복된다")
        return cls(
            company_id=raw["company_id"],
            company_name=raw["company_name"],
            label=raw["label"],
            profile=raw["profile"],
            articles=arts,
        )

    def get(self, ref: str) -> PolicyArticle:
        for a in self.articles:
            if a.ref == ref:
                return a
        raise KeyError(ref)
