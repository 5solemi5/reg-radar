"""법제처 신구법 비교(oldAndNew) 파서 — 진짜 변경점의 원천 (FR-005, BR-002).

법제처는 개정 전/후 조문을 나란히 주면서 **바뀐 부분을 `<P>...</P>`로 직접 표시**한다.
즉 '무엇이 바뀌었는가'는 추론할 필요 없이 공식 데이터가 알려준다. LLM은 물론
우리 diff 알고리즘조차 개입하지 않는다.

또한 응답에는 **변경된 조문만** 들어 있으므로, 분석 후보 선정 문제도 함께 풀린다.
132개 조문을 전부 LLM에 넣는 대신 실제로 바뀐 조문만 분석하면 된다.
"""

from __future__ import annotations

import re
from datetime import date
from xml.etree import ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field

from app.adapters.law.parser import LawParseError, _clean, _parse_date, _text

# 법제처가 변경 구간을 표시하는 태그
_CHANGE_MARK = re.compile(r"<P>(.*?)</P>", re.DOTALL)
# 조문 머리글: 제60조(연차 유급휴가) / 제24조의2(주민등록번호 처리의 제한)
_ARTICLE_HEAD = re.compile(r"^제(\d+)조(?:의(\d+))?\s*(?:\(([^)]*)\))?")
# 변경 없음 자리표시자: (생  략) / (현행과 같음) — 공백이 들쭉날쭉하다
_PLACEHOLDER = re.compile(r"\((?:생\s*략|현행과\s*같음|현행과\s*같\s*음)\)")


class OldNewVersionInfo(BaseModel):
    """구/신 법령 버전 메타."""

    model_config = ConfigDict(frozen=True)

    mst: str | None = None
    law_id: str | None = None
    law_name: str | None = None
    effective_date: date | None = None
    promulgation_date: date | None = None
    revision_type: str | None = None
    is_current: bool = False


class ChangedArticle(BaseModel):
    """실제로 개정된 조문 1건."""

    model_config = ConfigDict(frozen=True)

    article_no: str = Field(..., description="제60조, 제24조의2 형식")
    article_title: str | None = None
    old_text: str = Field("", description="개정 전 (자리표시자 제외)")
    new_text: str = Field("", description="개정 후 (자리표시자 제외)")
    additions: list[str] = Field(
        default_factory=list, description="법제처가 <P>로 표시한 개정 후 변경 구간"
    )
    deletions: list[str] = Field(
        default_factory=list, description="법제처가 <P>로 표시한 개정 전 변경 구간"
    )

    @property
    def has_marked_change(self) -> bool:
        return bool(self.additions or self.deletions)


class OldAndNewComparison(BaseModel):
    """신구법 비교 결과 전체."""

    old_version: OldNewVersionInfo
    new_version: OldNewVersionInfo
    changed_articles: list[ChangedArticle] = Field(default_factory=list)

    @property
    def law_name(self) -> str | None:
        return self.new_version.law_name or self.old_version.law_name

    @property
    def changed_article_numbers(self) -> list[str]:
        """분석 후보. 이 목록 밖의 조문은 이번 개정에서 바뀌지 않았다."""
        return [a.article_no for a in self.changed_articles]


def strip_change_marks(text: str) -> str:
    """`<P>` 태그만 제거하고 내용은 보존한다."""
    return text.replace("<P>", "").replace("</P>", "")


def extract_change_marks(text: str) -> list[str]:
    """`<P>`로 감싸인 변경 구간을 뽑는다."""
    return [_clean(m) for m in _CHANGE_MARK.findall(text) if _clean(m)]


def is_placeholder_only(text: str) -> bool:
    """'① ∼ ⑤ (생  략)' 처럼 내용 없이 생략만 표시한 줄인지."""
    without = _PLACEHOLDER.sub("", strip_change_marks(text))
    # 남은 것이 항·호 번호와 기호뿐이면 실질 내용이 없다
    return not re.sub(r"[\s①-⑳0-9.·∼~\-ㆍ,]", "", without)


def _version(node: ET.Element | None, *, current: bool) -> OldNewVersionInfo:
    if node is None:
        return OldNewVersionInfo(is_current=current)
    return OldNewVersionInfo(
        mst=_text(node, "법령일련번호"),
        law_id=_text(node, "법령ID"),
        law_name=_text(node, "법령명"),
        effective_date=_parse_date(_text(node, "시행일자")),
        promulgation_date=_parse_date(_text(node, "공포일자")),
        revision_type=_text(node, "제개정구분명"),
        is_current=(_text(node, "현행여부") or "").upper() == "Y",
    )


def _entries(container: ET.Element | None) -> dict[int, str]:
    """<조문 no="n">텍스트</조문> → {n: 텍스트}"""
    if container is None:
        return {}
    result: dict[int, str] = {}
    for node in container.findall("조문"):
        raw = (node.text or "").strip()
        no = node.get("no")
        if no and no.isdigit():
            result[int(no)] = raw
    return result


def parse_old_and_new(xml: str | bytes) -> OldAndNewComparison:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise LawParseError(f"신구법 비교 응답 파싱 실패: {exc}") from exc

    if root.tag != "OldAndNewService":
        raise LawParseError(f"예상치 못한 응답 루트: <{root.tag}>. MST/OC를 확인하세요.")

    old_entries = _entries(root.find("구조문목록"))
    new_entries = _entries(root.find("신조문목록"))

    # 구/신 목록은 no로 1:1 대응한다.
    buckets: dict[str, dict] = {}
    order: list[str] = []
    current_no: str | None = None
    current_title: str | None = None

    for no in sorted(set(old_entries) | set(new_entries)):
        old_raw = old_entries.get(no, "")
        new_raw = new_entries.get(no, "")

        # 조문 머리글을 만나면 소속 조문이 바뀐다.
        for candidate in (new_raw, old_raw):
            head = _ARTICLE_HEAD.match(strip_change_marks(candidate).lstrip())
            if head:
                main, branch, title = head.group(1), head.group(2), head.group(3)
                current_no = f"제{main}조의{branch}" if branch else f"제{main}조"
                current_title = title
                break

        if current_no is None:
            continue  # 조문 귀속이 확인되지 않은 조각은 버린다 (추측 금지)

        if current_no not in buckets:
            buckets[current_no] = {
                "title": current_title,
                "old": [], "new": [], "additions": [], "deletions": [],
            }
            order.append(current_no)

        bucket = buckets[current_no]
        if old_raw and not is_placeholder_only(old_raw):
            bucket["old"].append(_clean(strip_change_marks(old_raw)))
        if new_raw and not is_placeholder_only(new_raw):
            bucket["new"].append(_clean(strip_change_marks(new_raw)))
        bucket["deletions"].extend(extract_change_marks(old_raw))
        bucket["additions"].extend(extract_change_marks(new_raw))

    changed = [
        ChangedArticle(
            article_no=no,
            article_title=buckets[no]["title"],
            old_text="\n".join(buckets[no]["old"]),
            new_text="\n".join(buckets[no]["new"]),
            additions=buckets[no]["additions"],
            deletions=buckets[no]["deletions"],
        )
        for no in order
    ]
    # 법제처가 변경 구간을 표시하지 않은 조문은 실제 개정 대상이 아니다.
    changed = [a for a in changed if a.has_marked_change]

    return OldAndNewComparison(
        old_version=_version(root.find("구조문_기본정보"), current=False),
        new_version=_version(root.find("신조문_기본정보"), current=True),
        changed_articles=changed,
    )
