"""한국관광공사 TourAPI(KorService2) 수집기.

2026년 행정구역 개편으로 전남·광주는 법정동 코드 12(전남광주통합특별시)로 조회한다.
옛 areaCode(38/5) 방식은 일부만 조회되므로 쓰지 않는다.

실행 예)
  python -m scripts.collect_tourapi list        # 목록·축제·분류코드·시군구 (약 10회 호출)
  python -m scripts.collect_tourapi detail 900  # 소개글 상세 최대 900건 (이미 받은 건 건너뜀)

상세(detailCommon2)는 건별 호출이라 일일 트래픽 한도에 걸릴 수 있다.
한도 오류가 나면 멈추고, 다음 날 같은 명령(또는 scheduler.py)이 이어서 받는다.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from urllib.parse import unquote

import requests

from core.config import RAW, secret

BASE = "https://apis.data.go.kr/B551011/KorService2"
LDONG = "12"                      # 전남광주통합특별시
DETAIL_DIR = RAW / "detail"
DETAIL_DIR.mkdir(parents=True, exist_ok=True)
# 소개글을 받을 유형 (우선순위 순): 관광지·문화시설·레포츠·축제·쇼핑
DETAIL_TYPES = ["12", "14", "28", "15", "38"]


class QuotaExceeded(RuntimeError):
    pass


def call(endpoint: str, **params) -> dict:
    key = secret("DATA_GO_KR_KEY")
    if not key:
        raise RuntimeError("DATA_GO_KR_KEY 가 없습니다 (.streamlit/secrets.toml 또는 환경변수)")
    q = {**params, "serviceKey": unquote(key), "MobileOS": "ETC",
         "MobileApp": "NamdoON", "_type": "json"}
    for attempt in range(3):
        try:
            r = requests.get(f"{BASE}/{endpoint}", params=q, timeout=(10, 40))
            if r.status_code in (500, 502, 503, 504) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            text = r.text
            if "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in text or r.status_code == 429:
                raise QuotaExceeded(text[:200])
            r.raise_for_status()
            body = r.json()["response"]
            code = str(body["header"]["resultCode"])
            if code not in ("0000", "00"):
                if code == "22":
                    raise QuotaExceeded(body["header"].get("resultMsg"))
                raise RuntimeError(f"{endpoint} 오류 {code}: {body['header'].get('resultMsg')}")
            return body.get("body") or {}
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def items_of(body: dict) -> list[dict]:
    items = body.get("items") or {}
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    return items if isinstance(items, list) else []


def paged(endpoint: str, **params) -> list[dict]:
    rows, page = [], 1
    while True:
        body = call(endpoint, numOfRows=1000, pageNo=page, **params)
        got = items_of(body)
        rows.extend(got)
        total = int(body.get("totalCount") or 0)
        print(f"  {endpoint} p{page}: {len(got)}건 / 전체 {total}")
        if not got or page * 1000 >= total:
            return rows
        page += 1
        time.sleep(0.2)


def save(name: str, data) -> None:
    path = RAW / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"저장: {path.name} ({len(data)}건)")


def collect_list() -> None:
    stamp = datetime.now().isoformat(timespec="seconds")
    sigungu = paged("ldongCode2", lDongRegnCd=LDONG)
    save("sigungu.json", sigungu)
    places = paged("areaBasedList2", lDongRegnCd=LDONG, arrange="A")
    for p in places:
        p["collected_at"] = stamp
    save("places_list.json", places)
    fest = paged("searchFestival2", eventStartDate="20250101", lDongRegnCd=LDONG)
    save("festivals.json", fest)
    # 신 분류체계(lclsSystm) 코드 → 이름
    cats = paged("lclsSystmCode2", lclsSystmListYn="Y")
    save("lcls_codes.json", cats)


def collect_details(limit: int) -> None:
    places = json.loads((RAW / "places_list.json").read_text(encoding="utf-8"))
    order = {t: i for i, t in enumerate(DETAIL_TYPES)}
    todo = [p for p in places if str(p.get("contenttypeid")) in order
            and not (DETAIL_DIR / f"{p['contentid']}.json").exists()]
    # 이미지가 있는 관광지부터 (추천 카드 품질이 좋음)
    todo.sort(key=lambda p: (order[str(p["contenttypeid"])], not p.get("firstimage")))
    print(f"상세 미수집 {len(todo)}건 중 최대 {limit}건 수집")
    done = 0
    for p in todo[:limit]:
        try:
            body = call("detailCommon2", contentId=p["contentid"])
        except QuotaExceeded as e:
            print(f"일일 호출 한도 도달 → 중단 ({done}건 저장). 내일 이어서 실행하세요. {e}")
            break
        got = items_of(body)
        if got:
            (DETAIL_DIR / f"{p['contentid']}.json").write_text(
                json.dumps(got[0], ensure_ascii=False), encoding="utf-8")
            done += 1
        if done % 100 == 0 and done:
            print(f"  상세 {done}건")
        time.sleep(0.08)
    left = len(todo) - done
    print(f"상세 저장 {done}건, 남은 대상 {left}건")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "list"
    if mode == "list":
        collect_list()
    elif mode == "detail":
        collect_details(int(sys.argv[2]) if len(sys.argv) > 2 else 900)
    else:
        print(__doc__)
