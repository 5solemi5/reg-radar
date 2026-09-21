"""RAG 인덱스 구축.

법제처의 법령해석례·행정규칙·판례를 수집해 벡터 인덱스를 만든다.

    .venv/bin/python scripts/ingest_rag.py                    # 기본 검색어
    .venv/bin/python scripts/ingest_rag.py 개인정보 근로기준법   # 검색어 지정
    .venv/bin/python scripts/ingest_rag.py --status           # 인덱스 현황
"""

import asyncio
import sys

from app.core.config import get_settings
from app.rag.ingest import RagIngestor
from app.rag.store import build_store

# 프로필의 관심 영역과 대응한다 (app/services/law_selector.py).
DEFAULT_QUERIES = [
    "개인정보 보호법",
    "근로기준법",
    "산업안전보건법",
    "남녀고용평등",
    "전자상거래",
]


async def main() -> int:
    settings = get_settings()

    if "--status" in sys.argv:
        store = build_store(settings)
        print(f"▶ {settings.vector_store} · {settings.chroma_persist_dir}")
        print(f"  색인된 청크: {await store.count()}개")
        return 0

    if not settings.llm_enabled:
        print("✗ OPENAI_API_KEY가 필요합니다 (임베딩).")
        return 1
    if not settings.law_api_enabled:
        print("✗ LAW_API_OC가 필요합니다 (자료 수집).")
        return 1

    queries = [a for a in sys.argv[1:] if not a.startswith("--")] or DEFAULT_QUERIES
    print(f"▶ 검색어 {len(queries)}개: {', '.join(queries)}")
    print(f"▶ 저장소: {settings.vector_store} · {settings.chroma_persist_dir}\n")

    ingestor = RagIngestor(settings=settings)

    print("① 법제처에서 수집 (법령해석례·행정규칙·판례)")
    documents = await ingestor.collect(queries)
    by_type: dict[str, int] = {}
    for doc in documents:
        by_type[doc.doc_type.value] = by_type.get(doc.doc_type.value, 0) + 1
    print(f"   문서 {len(documents)}건 · {by_type}\n")

    if not documents:
        print("✗ 수집된 문서가 없습니다.")
        return 1

    print("② 청킹 · 임베딩 · 색인")
    report = await ingestor.index(documents)
    report.queries = queries
    print(f"   {report.summary()}")
    for message in report.errors:
        print(f"   ✗ {message}")

    print(f"\n✓ 인덱스 총 {await ingestor.store.count()}개 청크")
    print("\n샘플 문서:")
    for doc in documents[:5]:
        print(f"  · [{doc.doc_type.value}] {doc.title[:70]}")
        print(f"    {doc.agency} · {doc.published_at} · 관련법령={doc.related_law_names[:3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
