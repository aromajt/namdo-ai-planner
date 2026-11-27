"""AI 호출 없이 돌아가는 핵심 로직 테스트: python -m pytest -q"""
import sqlite3

import pytest

from core import db, geo, planner
from core.config import TOUR_DB
from core.retriever import _rrf, _tokens


# ---------------- 데이터베이스
def test_db_has_core_tables():
    con = sqlite3.connect(TOUR_DB)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"places", "festivals", "sigungu", "visitors_monthly", "demand", "meta"} <= tables
    assert con.execute("SELECT count(*) FROM places").fetchone()[0] > 3000
    assert con.execute("SELECT count(*) FROM sigungu").fetchone()[0] == 27


@pytest.mark.parametrize("text,expected", [
    ("여수", "여수시"), ("여수시", "여수시"), ("담양", "담양군"), ("광주 광산구", "광산구"), ("서울", None)])
def test_normalize_sigungu(text, expected):
    assert db.normalize_sigungu(text) == expected


def test_sql_injection_is_inert():
    # 키워드에 SQL 조각을 넣어도 바인딩 값으로만 처리되어 전체 조회가 되지 않는다
    df = db.places(keyword="' OR 1=1 --")
    assert df.empty


def test_db_is_read_only():
    with pytest.raises(Exception):
        with db._con() as con:
            con.execute("DELETE FROM places")


def test_evidence_numbers_are_from_db():
    ev = db.evidence_numbers("여수시", 11)
    assert ev["시군구"] == "여수시"
    assert "11월 혼잡 수준(평균 대비)" in ev
    assert isinstance(ev["외지인 일평균 추정 방문(전체 기간)"], int)


# ---------------- 거리·동선
def test_haversine_known_distance():
    # 서울시청 ↔ 부산시청 약 325km
    assert 320 < geo.haversine(37.5663, 126.9779, 35.1798, 129.0750) < 330


def test_order_route_visits_nearest_first():
    stops = [{"lat": 0, "lon": 0, "n": "A"}, {"lat": 0, "lon": 3, "n": "C"}, {"lat": 0, "lon": 1, "n": "B"}]
    assert [s["n"] for s in geo.order_route(stops)] == ["A", "B", "C"]


# ---------------- 검색
def test_korean_tokens_include_bigrams():
    toks = _tokens("대나무숲길")
    assert "대나무숲길" in toks and "대나" in toks and "숲길" in toks


def test_rrf_merges_rankings():
    from langchain_core.documents import Document
    a, b, c = (Document(page_content=x, metadata={"contentid": x}) for x in "abc")
    merged = _rrf([[a, b], [b, c]])
    assert merged[0].metadata["contentid"] == "b"   # 두 목록 모두 상위인 문서가 1위


# ---------------- 플래너 검증·보정 (LLM 없이)
def _state():
    cands = [{"key": f"P{i:02d}", "contentid": str(i), "title": f"장소{i}", "lat": 34.7 + i * 0.01,
              "lon": 127.7, "category": "관광지", "image": "", "indoor": False} for i in range(1, 7)]
    return {"parsed": {"days": 1, "pace": "보통"}, "candidates": cands, "attempts": 2}


def test_validator_flags_unknown_and_duplicate():
    st = _state()
    st["plan"] = {"days": [{"day": 1, "theme": "t", "stops": [
        {"key": "P01", "reason": "", "slot": "오전"}, {"key": "P01", "reason": "", "slot": "오후"},
        {"key": "X99", "reason": "", "slot": "저녁"}]}]}
    st.update(planner.route_agent(st))
    issues = planner.validator_agent(st)["issues"]
    assert any("X99" in i for i in issues) and any("중복" in i for i in issues)
    st["issues"] = issues
    assert planner.after_validate(st) == "repair"     # 재작성 2회를 넘겼으므로 규칙 보정으로


def test_repair_removes_duplicates_and_fills():
    st = _state()
    st["days"] = [{"day": 1, "theme": "t", "stops": [dict(st["candidates"][0], reason="", slot="오전"),
                                                     dict(st["candidates"][0], reason="", slot="오후")]}]
    out = planner.repair_agent(st)
    keys = [s["key"] for s in out["days"][0]["stops"]]
    assert len(keys) == len(set(keys)) >= 2
    assert out["issues"] == []


def test_graph_compiles_with_all_agents():
    g = planner.build_graph().get_graph()
    assert {"intake", "scout", "analyst", "weather", "planner", "route", "validator", "repair",
            "finalize"} <= set(g.nodes)


def test_evidence_sentence_uses_exact_db_numbers():
    ev = db.evidence_numbers("여수시", 11)
    text = planner.evidence_sentence(ev, 11)
    assert f"{ev['11월 외지인 일평균 추정 방문']:,}명" in text
    assert "관광빅데이터" in text
