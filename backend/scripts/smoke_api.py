"""API E2E 스모크 — 실행 중인 서버에 실제 요청을 보낸다.

    .venv/bin/python -m uvicorn app.main:app --port 8811 &
    .venv/bin/python scripts/smoke_api.py
"""

import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8811/api/v1"
USER = "demo-hr"

PROFILE = {
    "job": "HR 담당자 (채용·근태·취업규칙)",
    "industry": "IT 서비스",
    "company_size": "MEDIUM",
    "employee_count": 80,
    "interests": ["노동", "근로계약"],
}

BADGE = {"APPLICABLE": "🔴 해당", "HOLD": "🟡 보류", "NOT_APPLICABLE": "⚪ 무관"}


def main() -> int:
    api = httpx.Client(base_url=BASE, headers={"X-User-Id": USER}, timeout=30.0)

    print("① 헬스")
    health = api.get("/health").json()
    print(f"   env={health['env']} model={health['llm_model']} "
          f"law_api={health['law_api_configured']}")

    print("\n② 프로필 생성")
    r = api.put("/profile", json=PROFILE)
    if r.status_code != 200:
        print(f"   ✗ {r.status_code} {r.text[:300]}")
        return 1
    p = r.json()
    print(f"   {p['job']} · {p['industry']} · {p['employee_count']}명")

    print("\n③ 분석 실행")
    r = api.post("/analyses", json={"law_query": "근로기준법", "max_laws": 1})
    if r.status_code != 202:
        print(f"   ✗ {r.status_code} {r.text[:300]}")
        return 1
    analysis_id = r.json()["analysis_id"]
    print(f"   analysis_id={analysis_id}  (202 Accepted)")

    print("\n④ 상태 폴링")
    started = time.time()
    for attempt in range(60):
        analysis = api.get(f"/analyses/{analysis_id}").json()
        status = analysis["status"]
        if attempt % 5 == 0 or status in ("COMPLETED", "FAILED"):
            print(f"   [{time.time() - started:5.1f}s] {status}")
        if status in ("COMPLETED", "FAILED"):
            break
        time.sleep(2)

    if analysis["status"] == "FAILED":
        print(f"   ✗ 분석 실패: {analysis['error']}")
        return 1

    print(f"\n⑤ 분석 요약 (소요 {time.time() - started:.1f}s)")
    print(f"   법령 {analysis['laws_examined']}건 · 변경 조문 {analysis['articles_changed']}건")
    counts = analysis["counts"]
    print(f"   ACTION {counts['action']} · DECISION {counts['decision']} · "
          f"AWARENESS {counts['awareness']} · 보류 {counts['hold']} · "
          f"무관 {counts['not_applicable']} · 검증실패 {counts['rejected']}")

    print("\n⑥ 결과 목록 (대시보드 정렬)")
    results = api.get(f"/analyses/{analysis_id}/results").json()
    if not results["items"]:
        print("   (노출 대상 결과 없음 — 무관 포함해서 재조회)")
        results = api.get(
            f"/analyses/{analysis_id}/results", params={"include_not_applicable": True}
        ).json()
    for item in results["items"]:
        grade = f" · {item['action_grade']}" if item["action_grade"] else ""
        ev = item["legal_evidence"]
        print(f"   {BADGE.get(item['applicability'], '?')}{grade}  "
              f"{ev['law_name']} {ev['article_no']}({ev['article_title']})")
        print(f"      {item['ai_interpretation']['reason'][:120]}")

    if not results["items"]:
        print("   ✗ 결과가 없습니다.")
        return 1

    result_id = results["items"][0]["result_id"]

    print("\n⑦ 근거 조회 — 세 근거가 분리되어 있는지")
    ev = api.get(f"/results/{result_id}/evidence").json()
    legal = ev["legal_evidence"]
    print(f"   [법적 근거] {legal['law_name']} {legal['article_no']} "
          f"시행 {legal['effective_date']} · {legal['ministry']}")
    for span in legal["quoted_spans"][:2]:
        print(f"      검증된 인용: \"{span[:70]}\"")
    print(f"   [참고 자료] {len(ev['reference_evidence'])}건 (RAG는 W5에서 연결)")
    print(f"   [AI 해석 ] {ev['ai_interpretation']['reason'][:100]}")
    forbidden = [
        k for k in ("law_name", "article_no", "effective_date")
        if k in ev["ai_interpretation"]
    ]
    print(f"   AI 해석 블록의 공식 사실 필드: {forbidden or '없음 ✓'}")

    print("\n⑧ 저장 · 피드백")
    saved = api.post("/saved-regulations", json={"result_id": result_id, "note": "검토 필요"})
    print(f"   저장: {saved.status_code} → {saved.json()['law_name']} "
          f"{saved.json()['article_no']}")
    fb = api.post(f"/results/{result_id}/feedback", json={"helpful": True})
    print(f"   피드백: {fb.status_code}")

    print("\n⑨ 데이터 격리 확인")
    other = httpx.Client(base_url=BASE, headers={"X-User-Id": "someone-else"}, timeout=10.0)
    print(f"   남의 분석 조회: {other.get(f'/analyses/{analysis_id}').status_code} (404 기대)")
    print(f"   남의 결과 조회: {other.get(f'/results/{result_id}').status_code} (404 기대)")
    print(f"   남의 히스토리:  {other.get('/analyses').json()['total']}건 (0 기대)")

    print("\n✓ E2E 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
