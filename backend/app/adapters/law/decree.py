"""법률↔시행령 페어링 (ADR-025).

홀드아웃 평가(evaluation/README.md)에서 오답 6건이 **전부** 같은 원인이었다.
조문에 "대통령령으로 정한다"가 있으면, 그 위임이 적용 여부를 좌우하는지 세부
절차에 관한 것인지와 무관하게 보류가 나왔다. 최저임금법 제6조의 위임은 *산입
임금의 범위*에 관한 것이지 최저임금 지급 의무 자체를 좌우하지 않는데도
"조문만으로 확정할 수 없다"고 답한다. 위임 문구만 보이고 위임된 **내용**은
보이지 않으니 모델로서는 달리 할 수 있는 게 없다.

그래서 위임된 하위법령 조문을 찾아 같이 준다. "위임됐으니 모른다" 대신 실제
기준을 읽고 판정할 수 있게 된다.

역매핑은 시행령 조문이 모법을 직접 참조한다는 점을 이용한다. 최저임금법
시행령 제5조의2는 본문에 "법 제6조제4항에 따라"를 담고 있어, 거꾸로 모법
제6조에 딸린 조문임을 알 수 있다. 이 참조는 법제처 원문에 그대로 들어 있으므로
추론이 아니라 사실이다.
"""

from __future__ import annotations

import re

from app.adapters.law.models import LawArticle, LawSnapshot
from app.diff.korean import DELEGATION_VERB, HADA
from app.domain.context import DelegatedContext

# 시행령 조문이 모법을 참조하는 문구. 예: "법 제6조제4항에 따라", "법 제7조에 따른"
#
# 하위법령 본문에서 맨 '법'은 모법을 가리키는 관용 표기이고, 다른 법률은 「근로기준법」
# 처럼 낫표로 묶는다. 그래서 앞 글자가 한글이면(= 법령명의 꼬리면) 제외한다.
# 이렇게 하지 않으면 "근로기준법 제50조"를 모법 제50조로 잘못 색인해, 엉뚱한 조문을
# 근거로 붙이게 된다. 틀린 근거는 근거가 없는 것보다 나쁘다.
# '이 법'은 하위법령 자기 자신을 뜻하므로 함께 제외한다.
_BACK_REF = re.compile(r"(?<![가-힣])(?<!이\s)법\s*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")

# 하위법령이 모법을 처음 부를 때 쓰는 형태.
#   「파견근로자 보호 등에 관한 법률」(이하 "법"이라 한다) 제5조제1항
# 낫표가 끼어 있어 위 _BACK_REF가 잡지 못한다. 그런데 바로 이 자리가 위임을
# 이행하는 첫 문장인 경우가 많다. 실제로 파견법 시행령 제2조 ①("…란 별표1의
# 업무를 말한다")을 놓쳐 '기준을 확보했다'고 잘못 판단했다.
#
# '(이하 "법"이라 한다)'가 붙은 경우에만 인정한다. 그 괄호가 곧 "이 낫표 안이
# 모법이다"라는 선언이므로, 「근로기준법」 같은 타법 인용과 섞이지 않는다.
_SELF_DEFINED_REF = re.compile(
    r"「[^」]{2,60}」\s*\(\s*이하\s*[\"\u201c\u201d']?\s*법\s*[\"\u201c\u201d']?\s*이라\s*한다\s*\)"
    r"\s*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?"
)

# 조문 첫머리의 "제31조(제목)" 부분. 근거 절을 재기 전에 떼어낸다.
_ARTICLE_HEAD = re.compile(r"^\s*제\s*\d+\s*조(?:\s*의\s*\d+)?\s*(?:\([^)]*\))?\s*")

# 항 번호. 하위법령은 항마다 근거를 다시 밝히는 일이 많다.
_PARAGRAPH_MARK = re.compile(r"[①-⑳]")

BASIS_WINDOW = 60
"""각 항의 앞부분 중 '근거 절'로 볼 길이.

이행 조문은 첫머리에서 근거를 밝힌다.
  "제16조(안전관리자의 선임 등) ① 법 제17조제1항에 따라 ... 는 별표 3과 같다"

반면 지나가는 참조는 호·목 안쪽에 묻혀 있다.
  "제30조(안전성 확보 조치) ① ... 1. ... 나. 법 제31조에 따른 개인정보 보호책임자의 지정"

개인정보 보호법 제31조를 조회했을 때 실제로 이 차이가 문제가 됐다. 시행령
제13조·제14조의2·제30조가 모두 '법 제31조'를 언급하지만 위임을 이행하는 조문은
제32조의2 하나뿐인데, 넷을 다 붙이니 엉뚱한 조문 셋이 근거로 들어갔다.
"""

# 하위법령이 기준을 또 다른 곳으로 넘기는 표현. 이게 있으면 조문을 확보해도
# 기준은 여전히 손에 없다. 별표는 법제처 조문 본문에 딸려 오지 않는다.
_STILL_UNRESOLVED = re.compile(
    rf"별표\s*\d+"
    rf"|(?:대통령령|부령|총리령|고시)(?:으로|로|이|에서)?\s*{DELEGATION_VERB}"
    rf"|고시{HADA}"
)

# 큰따옴표로 묶인 구간. 이행 조문에서 정의 대상을 감싸는 데 쓰인다.
_QUOTED = re.compile("[\"\u201c\u201d][^\"\u201c\u201d]{0,120}[\"\u201c\u201d]")

# 모법 조문이 위임하는 하위법령의 종류. detect_delegation과 짝을 이룬다.
DECREE_SUFFIX_BY_TARGET: dict[str, tuple[str, ...]] = {
    "대통령령": ("시행령",),
    "부령": ("시행규칙",),
    "총리령": ("시행규칙",),
    "고시": (),  # 고시·훈령은 별도 target(admrul)이라 여기서 다루지 않는다
}

MAX_PAIRED_ARTICLES = 4
"""한 모법 조문에 붙일 하위법령 조문 수 상한.

최저임금법 시행령 제11조처럼 여러 모법 조문을 한꺼번에 참조하는 조문이 있어
상한 없이 붙이면 프롬프트가 조문 원문보다 커진다. 판정에 필요한 것은 위임된
기준이지 하위법령 전체가 아니다.
"""


def decree_names(law_name: str, targets: list[str]) -> list[str]:
    """모법 이름과 위임 대상으로 찾아야 할 하위법령 이름을 만든다.

    법제처는 하위법령을 "{모법명} 시행령" / "{모법명} 시행규칙"으로 명명한다.
    """
    names: list[str] = []
    for target in targets:
        for suffix in DECREE_SUFFIX_BY_TARGET.get(target, ()):
            name = f"{law_name} {suffix}"
            if name not in names:
                names.append(name)
    return names


def _normalize_ref(main: str, branch: str | None) -> str:
    return f"제{int(main)}조의{int(branch)}" if branch else f"제{int(main)}조"


def back_references(text: str, *, basis_only: bool = True) -> set[str]:
    """하위법령 조문이 참조하는 모법 조문번호를 뽑는다.

    `basis_only`면 각 항의 앞부분(근거 절)만 본다. 조문 전체를 보면 "법 제31조에
    따른 개인정보 보호책임자"처럼 다른 조문을 설명하려고 스쳐 지나간 참조까지
    잡혀, 위임과 무관한 조문이 근거로 붙는다.
    """
    if not text:
        return set()
    def found_in(chunk: str) -> set[str]:
        return {
            _normalize_ref(m.group(1), m.group(2))
            for pattern in (_BACK_REF, _SELF_DEFINED_REF)
            for m in pattern.finditer(chunk)
        }

    if not basis_only:
        return found_in(text)

    body = _ARTICLE_HEAD.sub("", text, count=1)
    # 항이 없으면(제1항만 있는 조문) 본문 전체가 하나의 항이다.
    starts = [m.start() for m in _PARAGRAPH_MARK.finditer(body)] or [0]
    if starts[0] != 0:
        starts.insert(0, 0)

    refs: set[str] = set()
    for start in starts:
        clause = body[start : start + BASIS_WINDOW]
        refs |= found_in(clause)
    return refs


_SENTENCE_SPLIT = re.compile(r"(?<=다\.)\s+|[①-⑳]|\n")


def _basis_sentences(text: str, parent_article_no: str | None) -> list[str]:
    """모법을 근거로 대는 문장만 골라낸다.

    하위법령 조문은 길고, 호·목 안에는 이 위임과 무관한 별표·고시 참조가 흔하다.
    위임이 해소됐는지는 **위임을 이행하는 문장**에서 봐야 한다.
    """
    segments = [s for s in _SENTENCE_SPLIT.split(text) if s and s.strip()]
    matched = [
        s for s in segments
        if (parent_article_no in back_references(s, basis_only=False))
        if parent_article_no
    ]
    if matched:
        return matched
    # 근거 문장을 특정하지 못하면 조문 전체를 본다.
    #
    # 첫 문장만 보게 했더니 조문제목만 훑고 "기준 있음"으로 통과했다. 파견법
    # 시행령 제2조가 그랬다 — 정작 별표로 넘기는 ①항을 못 보고 보류가 풀렸다.
    # 어디가 근거인지 모르겠으면 넓게 보는 쪽이 안전하다. 놓치는 것이 보류보다
    # 나쁘기 때문이다 (NFR-003).
    return segments or [text]


def resolves_criterion(text: str, parent_article_no: str | None = None) -> bool:
    """이 하위법령 조문이 기준을 실제로 담고 있는가.

    "별표 3과 같다"로 넘기면 기준은 별표에 있고 별표는 조문 본문에 딸려 오지
    않는다. 산업안전보건법 제17조에서 실제로 이 일이 났다 — 시행령 제16조를
    붙였더니 모델이 "별표 3"만 보고 150인 제조업을 무관으로 판정했다. 보류보다
    나쁜 결과다. 기준을 못 담은 조문은 확보하지 못한 것으로 친다.

    **위임을 이행하는 문장만 본다.** 조문 전체를 보면 호·목 안의 무관한 별표·고시
    참조까지 걸려 기능이 통째로 꺼진다. 실측에서 그렇게 됐다 — 중대재해처벌법
    시행령 제4조는 "법 제4조제1항제1호에 따른 조치의 구체적인 사항은 다음 각 호와
    같다"로 기준을 **담고 있는데**, 한참 뒤 호 안의 "별표 1" 때문에 미해소로 잡혔다.
    반면 산업안전보건법 시행령 제16조는 근거 문장 자체가 "…상시근로자 수는 별표
    3과 같다"이므로 여전히 미해소다. 이 차이를 문장 단위로 가른다.

    따옴표 안은 먼저 지운다. 하위법령이 위임을 이행하는 전형적인 문장이
    `법 제31조제8항에서 "대통령령으로 정하는 공동의 사업"이란 ...`인데, 여기서
    따옴표 안의 '대통령령으로 정하는'은 **정의되는 대상**이지 또 다른 위임이
    아니다. 지우지 않으면 이행 조문이 전부 미해소로 잡혀 기능이 통째로 꺼진다.
    """
    if not text:
        return False
    for sentence in _basis_sentences(text, parent_article_no):
        if _STILL_UNRESOLVED.search(_QUOTED.sub(" ", sentence)):
            return False
    return True


def build_back_reference_index(decree: LawSnapshot) -> dict[str, list[LawArticle]]:
    """하위법령 전체를 훑어 '모법 조문번호 → 하위법령 조문들' 색인을 만든다.

    한 하위법령 조문이 여러 모법 조문을 참조할 수 있으므로 다대다다.
    """
    index: dict[str, list[LawArticle]] = {}
    for article in decree.articles:
        if article.is_supplementary:
            continue  # 부칙은 경과조치라 판정 기준이 아니다
        for ref in back_references(article.original_text):
            index.setdefault(ref, []).append(article)
    return index


def _bigrams(text: str | None) -> set[str]:
    cleaned = re.sub(r"[^가-힣A-Za-z0-9]", "", text or "")
    return {cleaned[i : i + 2] for i in range(len(cleaned) - 1)}


def _title_overlap(parent_title: str | None, decree_title: str | None) -> float:
    """조문제목이 얼마나 같은 주제를 가리키는지 (자카드 유사도).

    형태소 분석 없이 글자 2-gram으로 잰다. "사업주의 장애인 고용 의무"와
    "사업주의 의무고용률"은 겹치고 "공사 실적액의 산정 등"은 겹치지 않는다.
    이 정도면 1순위를 고르는 데 충분하고, 사전이나 외부 의존성도 필요 없다.
    """
    a, b = _bigrams(parent_title), _bigrams(decree_title)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def pair_articles(
    parent_article_no: str,
    parent_article_title: str | None,
    decree: LawSnapshot,
    *,
    limit: int = MAX_PAIRED_ARTICLES,
) -> list[DelegatedContext]:
    """모법 조문 1건에 딸린 하위법령 조문을 찾는다.

    두 가지 신호를 쓰되 정밀도 순으로 적용한다.

    1. **역참조** — 하위법령 본문의 "법 제6조". 원문에 적힌 사실이라 가장 강하다.
    2. **조문제목 일치** — 최저임금법 제11조(주지 의무) ↔ 시행령 제11조(주지 의무).
       역참조가 없는 조문을 건지지만, 제목이 같아도 무관할 수 있어 2순위다.

    조번호만 같은 경우(모법 제5조 ↔ 시행령 제5조)는 쓰지 않는다. 시행령의 조번호는
    모법과 독립적으로 매겨지므로 우연의 일치가 흔하고, 틀린 근거를 붙이는 것은
    근거를 못 붙이는 것보다 나쁘다.
    """
    index = build_back_reference_index(decree)

    # 어느 것이 '그 위임을 이행하는 조문'인지 정하는 순서다. 맨 앞 조문으로 보류
    # 해제를 결정하므로 순서가 곧 판정을 바꾼다.
    #
    #   1. 조문제목이 모법 조문제목과 겹칠수록 앞. 장애인고용법 제28조(사업주의
    #      장애인 고용 의무)를 조회하면 시행령 제25조(사업주의 의무고용률)가
    #      제24조(공사 실적액의 산정 등)보다 먼저 와야 하는데, 참조 수가 같아
    #      조문번호 순으로 밀려 제24조가 1순위였다. 엉뚱한 조문으로 보류 여부를
    #      결정하고 있었다.
    #   2. 참조하는 모법 조문이 적을수록 앞 (그 조문 전용 규정일 가능성이 높다).
    by_specificity = sorted(
        index.get(parent_article_no, []),
        key=lambda a: (
            -_title_overlap(parent_article_title, a.article_title),
            len(back_references(a.original_text)),
            a.article_no,
        ),
    )
    matched: list[tuple[LawArticle, str]] = [
        (article, "back_reference") for article in by_specificity
    ]

    seen = {article.article_no for article, _ in matched}
    if parent_article_title:
        target_title = parent_article_title.strip()
        for article in decree.articles:
            if article.is_supplementary or article.article_no in seen:
                continue
            if (article.article_title or "").strip() == target_title:
                matched.append((article, "article_title"))
                seen.add(article.article_no)

    return [
        DelegatedContext(
            law_id=decree.law_id,
            law_name=decree.law_name,
            law_type=decree.law_type,
            article_no=article.article_no,
            article_title=article.article_title,
            original_text=article.original_text,
            source_url=decree.source_url,
            matched_by=matched_by,
            resolves_criterion=resolves_criterion(
                article.original_text, parent_article_no
            ),
        )
        for article, matched_by in matched[:limit]
    ]
