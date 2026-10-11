"""법령 조문 → 사내 규정 후보 검색 (결정적, 임베딩 없음).

LLM에 사내 규정집 전체를 넣지 않는다(비용·주의 분산). 먼저 코드가 후보를 좁히고,
LLM은 그 후보 중에서 영향 여부만 판단한다. 후보에 정답이 없으면 LLM도 찾을 수 없으므로
**검색 재현율**을 따로 잰다(평가 policy_impact).

방식: 한국어 글자 2-gram TF-IDF 코사인. 형태소 분석기 없이도 "배우자 출산휴가", "채용서류"처럼
법령과 규정이 같은 용어를 쓰는 경우를 잘 잡는다. 같은 입력이면 항상 같은 순서다.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from app.policies.models import PolicyArticle, PolicyCorpus

_KEEP = re.compile(r"[가-힣A-Za-z0-9]")
# 법령·규정 어디에나 나와서 변별력이 없는 2-gram
_STOP = {
    "하여", "여야", "아니", "니한", "한다", "에는", "으로",
    "에게", "하는", "경우", "등의", "또는", "있다",
}


def bigrams(text: str) -> list[str]:
    chars = "".join(c if _KEEP.match(c) else " " for c in text)
    grams = []
    for word in chars.split():
        grams += [word[i : i + 2] for i in range(len(word) - 1)]
    return [g for g in grams if g not in _STOP]


class PolicyRetriever:
    def __init__(self, corpus: PolicyCorpus):
        self.corpus = corpus
        docs = [Counter(bigrams(f"{a.policy_title} {a.title} {a.text}")) for a in corpus.articles]
        n = len(docs)
        df = Counter(g for d in docs for g in d)
        self.idf = {g: math.log((n + 1) / (c + 1)) + 1.0 for g, c in df.items()}
        self.vecs = [self._weigh(d) for d in docs]

    def _weigh(self, tf: Counter) -> dict[str, float]:
        v = {g: (1 + math.log(c)) * self.idf.get(g, 0.0) for g, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {g: x / norm for g, x in v.items()}

    def search(
        self, query: str, k: int = 5, min_score: float = 0.05
    ) -> list[tuple[PolicyArticle, float]]:
        q = self._weigh(Counter(g for g in bigrams(query) if g in self.idf))
        scored = [
            (art, sum(w * vec.get(g, 0.0) for g, w in q.items()))
            for art, vec in zip(self.corpus.articles, self.vecs, strict=True)
        ]
        scored.sort(key=lambda t: (-t[1], t[0].ref))
        return [(a, round(s, 6)) for a, s in scored[:k] if s >= min_score]
