"""RAG 파이프라인 테스트 (FR-013, FR-014, BR-004, BR-005).

핵심은 두 가지다.
  1. 참고자료가 없는 것은 **정상 상태**이며 분석을 막지 않는다 (BR-005).
  2. 참고자료는 법적 근거와 섞이지 않는다 (BR-004).
"""

import datetime as dt

import pytest

from app.domain.context import LegalContext, UserContext
from app.domain.enums import CompanySize, DocType
from app.rag.chunking import chunk_document, split_text
from app.rag.embeddings import EmbeddingUnavailableError
from app.rag.loaders import extract_law_names
from app.rag.models import RagChunk, RagDocument, RetrievedChunk
from app.rag.retriever import MIN_SCORE, NullRetriever, Retriever
from app.rag.store import InMemoryVectorStore

LAW = LegalContext(
    law_id="011357",
    law_name="개인정보 보호법",
    article_no="제23조",
    article_title="민감정보의 처리 제한",
    effective_date=dt.date(2026, 9, 11),
    ministry="개인정보보호위원회",
    original_text="① 개인정보처리자는 사상·신념 등 민감정보를 처리하여서는 아니 된다.",
)

USER = UserContext(
    job="HR 담당자", industry="IT 서비스",
    company_size=CompanySize.MEDIUM, employee_count=80,
)


def a_document(doc_id: str = "expc-1", **kwargs) -> RagDocument:
    base = dict(
        doc_id=doc_id,
        title="민감정보 처리 관련 법령해석례",
        body="[질의요지] 민감정보를 위탁 처리할 수 있는지. " * 10
        + "[회답] 별도 동의를 받아야 합니다. " * 10,
        doc_type=DocType.INTERPRETATION,
        source="https://www.law.go.kr/DRF/lawService.do?target=expc&ID=1",
        agency="법제처",
        published_at=dt.date(2026, 3, 1),
        related_law_names=["개인정보 보호법"],
    )
    return RagDocument(**{**base, **kwargs})


class FakeEmbedder:
    """결정적 임베딩. 단어 집합 기반이라 네트워크 없이 유사도가 의미를 갖는다."""

    VOCAB = ["민감정보", "개인정보", "동의", "위탁", "근로", "휴가", "안전", "식품"]

    def __init__(self, fail: bool = False):
        self.fail = fail

    @property
    def dimensions(self) -> int:
        return len(self.VOCAB)

    def _vector(self, text: str) -> list[float]:
        return [1.0 if word in text else 0.0 for word in self.VOCAB] or [0.0]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise EmbeddingUnavailableError("테스트용 실패")
        return [self._vector(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        if self.fail:
            raise EmbeddingUnavailableError("테스트용 실패")
        return self._vector(text)


@pytest.fixture
def store():
    return InMemoryVectorStore()


class TestChunking:
    def test_문서를_청크로_자른다(self):
        chunks = chunk_document(a_document())
        assert chunks
        assert all(isinstance(c, RagChunk) for c in chunks)

    def test_제목이_각_청크에_붙는다(self):
        """검색된 조각만 봐도 무슨 문서인지 알 수 있어야 한다."""
        for chunk in chunk_document(a_document()):
            assert chunk.title in chunk.text

    def test_metadata가_청크로_승계된다(self):
        chunk = chunk_document(a_document())[0]
        assert chunk.doc_type is DocType.INTERPRETATION
        assert chunk.source.startswith("https://")
        assert chunk.agency == "법제처"
        assert chunk.related_law_names == ["개인정보 보호법"]

    def test_같은_내용은_같은_청크_id를_낳는다(self):
        """다시 색인해도 중복이 쌓이지 않아야 한다."""
        first = chunk_document(a_document())
        second = chunk_document(a_document())
        assert [c.chunk_id for c in first] == [c.chunk_id for c in second]

    def test_질의_회답_경계에서_자른다(self):
        pieces = split_text("[질의요지] " + "가" * 500 + " [회답] " + "나" * 500)
        assert len(pieces) >= 2

    def test_빈_본문은_청크가_없다(self):
        assert split_text("") == []

    def test_너무_짧은_조각은_버린다(self):
        assert split_text("짧음") == []


class TestLawNameExtraction:
    def test_인용된_법령명을_뽑는다(self):
        names = extract_law_names("「개인정보 보호법」 제23조에 따라")
        assert names == ["개인정보 보호법"]

    def test_여러_법령을_모두_뽑는다(self):
        names = extract_law_names("「개인정보 보호법」과 「근로기준법」 관련")
        assert set(names) == {"개인정보 보호법", "근로기준법"}

    def test_중복은_한_번만(self):
        assert extract_law_names("「근로기준법」 「근로기준법」") == ["근로기준법"]


class TestVectorStore:
    async def test_저장후_검색(self, store):
        embedder = FakeEmbedder()
        chunks = chunk_document(a_document())
        await store.upsert(chunks, await embedder.embed([c.text for c in chunks]))

        results = await store.search(await embedder.embed_query("민감정보 동의"), top_k=3)
        assert results
        assert isinstance(results[0], RetrievedChunk)

    async def test_법령명_필터가_동작한다(self, store):
        """FR-013. 관련 없는 법령의 해석례가 섞이면 오해를 만든다."""
        embedder = FakeEmbedder()
        for doc in (
            a_document("expc-1", related_law_names=["개인정보 보호법"]),
            a_document("expc-2", related_law_names=["근로기준법"],
                       body="[질의요지] 연차휴가 근로 산정. " * 10),
        ):
            chunks = chunk_document(doc)
            await store.upsert(chunks, await embedder.embed([c.text for c in chunks]))

        results = await store.search(
            await embedder.embed_query("민감정보"), top_k=5, law_names=["개인정보 보호법"]
        )
        assert results
        assert all("개인정보 보호법" in r.chunk.related_law_names for r in results)

    async def test_시행령도_부분일치로_잡힌다(self, store):
        embedder = FakeEmbedder()
        doc = a_document("expc-3", related_law_names=["개인정보 보호법 시행령"])
        chunks = chunk_document(doc)
        await store.upsert(chunks, await embedder.embed([c.text for c in chunks]))

        results = await store.search(
            await embedder.embed_query("민감정보"), top_k=5, law_names=["개인정보 보호법"]
        )
        assert results

    async def test_문서유형_필터(self, store):
        embedder = FakeEmbedder()
        doc = a_document("admrul-1", doc_type=DocType.GUIDE)
        chunks = chunk_document(doc)
        await store.upsert(chunks, await embedder.embed([c.text for c in chunks]))

        assert await store.search(
            await embedder.embed_query("민감정보"), doc_types=["GUIDE"]
        )
        assert not await store.search(
            await embedder.embed_query("민감정보"), doc_types=["CASE"]
        )

    async def test_빈_저장소는_빈_결과(self, store):
        assert await store.search(await FakeEmbedder().embed_query("무엇"), top_k=5) == []


class TestRetriever:
    async def _seeded(self, store) -> Retriever:
        embedder = FakeEmbedder()
        chunks = chunk_document(a_document())
        await store.upsert(chunks, await embedder.embed([c.text for c in chunks]))
        return Retriever(embedder, store, top_k=3)

    async def test_관련_참고자료를_찾는다(self, store):
        retriever = await self._seeded(store)
        results = await retriever.retrieve(LAW, USER)
        assert results
        assert results[0].doc_type is DocType.INTERPRETATION

    async def test_RagContext에_출처_metadata가_모두_있다(self, store):
        """FR-013. 출처를 모르는 참고자료는 보여줄 수 없다."""
        retriever = await self._seeded(store)
        doc = (await retriever.retrieve(LAW, USER))[0]
        assert doc.source.startswith("https://")
        assert doc.agency == "법제처"
        assert doc.published_at == dt.date(2026, 3, 1)
        assert doc.doc_type is DocType.INTERPRETATION
        assert doc.snippet

    async def test_질의에_조문_원문_전체를_넣지_않는다(self):
        """원문이 길면 형식적 문구가 유사도를 지배해 해석례가 밀린다."""
        query = Retriever.build_query(LAW, USER)
        assert LAW.law_name in query
        assert LAW.article_title in query
        assert USER.industry in query
        assert len(query) < len(LAW.law_name) + len(LAW.original_text) + 400


class TestEmptyIsNormal:
    """BR-005. 참고자료 없음은 오류가 아니다."""

    async def test_인덱스가_비면_빈_목록(self, store):
        retriever = Retriever(FakeEmbedder(), store, top_k=3)
        assert await retriever.retrieve(LAW, USER) == []

    async def test_임베딩_실패해도_분석은_계속된다(self, store):
        retriever = Retriever(FakeEmbedder(fail=True), store, top_k=3)
        assert await retriever.retrieve(LAW, USER) == []

    async def test_저장소_오류도_흡수한다(self):
        class BrokenStore:
            async def search(self, *args, **kwargs):
                raise RuntimeError("인덱스 손상")

        retriever = Retriever(FakeEmbedder(), BrokenStore(), top_k=3)
        assert await retriever.retrieve(LAW, USER) == []

    async def test_유사도가_낮으면_제외한다(self, store):
        """관련 없는 참고자료는 없느니만 못하다 — 근거로 오해될 수 있다."""
        embedder = FakeEmbedder()
        # 법령명 필터는 통과하지만 내용이 전혀 다른 문서.
        # 제목에도 질의 어휘가 없어야 유사도가 실제로 낮아진다.
        doc = a_document(
            "expc-9",
            title="식품 위생 관련 해석례",
            related_law_names=["개인정보 보호법"],
            body="[질의요지] 식품 안전 기준에 관한 질의입니다. " * 10,
        )
        chunks = chunk_document(doc)
        await store.upsert(chunks, await embedder.embed([c.text for c in chunks]))

        raw = await store.search(await embedder.embed_query("민감정보 동의 위탁"), top_k=5)
        retriever = Retriever(embedder, store, top_k=5)
        results = await retriever.retrieve(LAW, USER)

        # 저장소는 뭔가 돌려줬지만 유사도 기준에서 걸러졌다
        assert raw and raw[0].score < MIN_SCORE
        assert results == []

    async def test_NullRetriever는_항상_빈_목록(self):
        assert await NullRetriever().retrieve(LAW, USER) == []


class TestEvidenceSeparation:
    """BR-004. 참고자료는 법적 근거가 아니다."""

    def test_RagContext는_법적_근거_필드를_갖지_않는다(self):
        from app.domain.context import RagContext

        forbidden = {"law_name", "article_no", "effective_date", "original_text"}
        assert not (forbidden & set(RagContext.model_fields))

    async def test_프롬프트에서_참고자료로_라벨링된다(self, store):
        from app.ai.context_builder import render_rag_block

        embedder = FakeEmbedder()
        chunks = chunk_document(a_document())
        await store.upsert(chunks, await embedder.embed([c.text for c in chunks]))
        docs = await Retriever(embedder, store, top_k=2).retrieve(LAW, USER)

        block = render_rag_block(docs)
        assert "[R1]" in block
        assert "법제처" in block
