"""LangGraph 멀티에이전트 여행 플래너.

흐름
  intake(조건 해석) → scout(후보 검색) ─┬→ analyst(수요·혼잡 근거) ─┬→ planner(일정 작성)
                                      └→ weather(날씨 예보)    ─┘        ↓
                    finalize ← validator(DB 검증) ← route(동선 정렬) ←───┘
                       ↑          └─ 문제 있으면 planner로 되돌림(최대 2회)
                       └── repair(규칙 보정) ← 2회 넘으면

환각 방지: 플래너는 후보 목록의 contentid 만 고를 수 있고, 이름·좌표·사진은 DB에서 다시 붙인다.
"""
from __future__ import annotations

import json
import operator
from datetime import date, timedelta
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field

from core import db, geo, retriever, weather
from core.config import MAX_INPUT_CHARS
from core.llm import UsageLogger, chat

INDOOR_TYPES = {"14", "38"}          # 문화시설·쇼핑 (비 오는 날 우선)
MAX_ATTEMPTS = 2


# ---------------------------------------------------------------- 상태
class PlanState(TypedDict, total=False):
    request: str
    form: dict
    parsed: dict
    candidates: list[dict]
    evidence: dict
    evidence_text: str
    festivals: list[dict]
    weather: list[dict]
    plan: dict
    days: list[dict]
    issues: list[str]
    attempts: int
    error: str
    trace: Annotated[list[str], operator.add]     # 에이전트 활동 기록(병렬 노드가 함께 추가)


# ---------------------------------------------------------------- 구조화 출력 스키마
class Intake(BaseModel):
    sigungu: str = Field(description="여행할 시군구 이름. 예: 여수시, 담양군, 동구. 모르면 빈 문자열")
    days: int = Field(description="여행 일수(1~4). '1박 2일'이면 2", ge=1, le=4)
    companion: str = Field(description="동행 유형: 혼자/연인/친구/가족(아이)/부모님/단체 중 하나")
    themes: list[str] = Field(description="관심 테마 키워드 1~4개. 예: 바다, 역사, 산책, 체험, 사진, 맛집")
    pace: Literal["여유", "보통", "알차게"] = Field(description="일정 강도")
    avoid_crowd: bool = Field(description="붐비는 곳을 피하고 싶다는 뜻이 있으면 true")


class Stop(BaseModel):
    key: str = Field(description="반드시 후보 목록에 있는 후보 번호 (예: P03)")
    reason: str = Field(description="이 장소를 고른 이유 1문장 (동행·테마와 연결)")
    slot: Literal["오전", "점심 후", "오후", "저녁"] = Field(description="방문 시간대")


class DayPlan(BaseModel):
    day: int
    theme: str = Field(description="그날의 한 줄 주제")
    stops: list[Stop]


class Plan(BaseModel):
    title: str = Field(description="여행 일정 제목")
    summary: str = Field(description="일정 전체 소개 2문장")
    days: list[DayPlan]
    tips: list[str] = Field(description="여행 팁 2~3개. 입장료·운영시간처럼 모르는 정보는 단정하지 말 것")


def _structured(schema, temperature: float):
    llm = chat(temperature=temperature)
    try:
        return llm.with_structured_output(schema)
    except NotImplementedError:
        return llm.with_structured_output(schema, method="json_schema")


def _cfg(state: PlanState, feature: str) -> dict:
    return {"callbacks": [UsageLogger(feature, state.get("request", ""))]}


# ---------------------------------------------------------------- 노드(에이전트)
def intake_agent(state: PlanState) -> PlanState:
    form = state.get("form", {})
    text = (state.get("request") or "")[:MAX_INPUT_CHARS]
    prompt = (
        "너는 전남·광주 여행 상담원이다. 사용자 요청과 입력 폼을 읽고 여행 조건을 정리해라.\n"
        f"선택 가능한 시군구: {', '.join(db.sigungu_names())}\n"
        f"입력 폼: {json.dumps(form, ensure_ascii=False)}\n사용자 요청: {text}\n"
        "폼 값이 있으면 폼을 우선한다. 지역명이 '여수'처럼 짧아도 목록의 정식 이름(여수시)으로 답해라."
    )
    out: Intake = _structured(Intake, 0).invoke(prompt, config=_cfg(state, "planner.intake"))
    parsed = out.model_dump()
    parsed["sigungu"] = db.normalize_sigungu(parsed["sigungu"]) or db.normalize_sigungu(form.get("sigungu", ""))
    start = form.get("start_date") or (date.today() + timedelta(days=7)).isoformat()
    parsed["start_date"] = str(start)
    parsed["month"] = int(str(start)[5:7])
    if not parsed["sigungu"]:
        return {"parsed": parsed, "error": "여행할 지역(시군구)을 찾지 못했습니다. 예: 여수, 담양, 광주 동구",
                "trace": ["🧭 조건 해석: 지역을 알 수 없어 중단"]}
    return {"parsed": parsed, "trace": [
        f"🧭 조건 해석: {parsed['sigungu']} · {parsed['days']}일 · {parsed['companion']} · "
        f"테마 {', '.join(parsed['themes'])}" + (" · 혼잡 회피" if parsed["avoid_crowd"] else "")]}


def scout_agent(state: PlanState) -> PlanState:
    p = state["parsed"]
    sgg = p["sigungu"]
    base = db.visit_candidates(sgg)
    query = " ".join(p["themes"]) + f" {p['companion']} 여행"
    hits = retriever.search(query, k=25, sigungu=sgg, kinds=("place",), rerank=False)
    hit_ids = [d.metadata["contentid"] for d in hits]
    rank = {cid: i for i, cid in enumerate(hit_ids)}
    base = base.assign(_score=base.contentid.map(lambda c: rank.get(c, 999)))
    # 테마 검색 상위 + 사진 있는 곳 우선, 최대 30곳
    base = base.sort_values(["_score", "image"], ascending=[True, False]).head(30)
    cands = [{
        "key": f"P{i + 1:02d}", "contentid": r.contentid, "title": r.title, "type_id": r.type_id,
        "category": "/".join(x for x in [r.type_name, r.cat3] if x),
        "lat": r.lat, "lon": r.lon, "image": r.thumb or r.image,
        "overview": (r.overview or "")[:160], "indoor": r.type_id in INDOOR_TYPES,
    } for i, r in enumerate(base.itertuples())]
    return {"candidates": cands,
            "trace": [f"🔎 후보 탐색: {sgg} 방문지 {len(cands)}곳 (하이브리드 검색으로 테마 적합도 정렬)"]}


def evidence_sentence(nums: dict, month: int) -> str:
    """DB 수치를 그대로 옮긴 근거 문장 (반올림 외 가공 없음)."""
    s = nums["시군구"]
    parts = []
    mk = f"{month}월 외지인 일평균 추정 방문"
    if mk in nums:
        parts.append(f"{s}의 {month}월 외지인 방문은 하루 평균 약 {nums[mk]:,}명(추정)으로, "
                     f"전체 기간 평균의 {nums[f'{month}월 혼잡 수준(평균 대비)']} 수준입니다.")
    if "가장 한산한 달" in nums:
        parts.append(f"자료 기간({nums['자료 기간']}) 중 가장 한산한 달은 {nums['가장 한산한 달']}, "
                     f"가장 붐빈 달은 {nums['가장 붐빈 달']}입니다.")
    stay = [(k, v) for k, v in nums.items() if k.startswith("[체류] 숙박 비중")]
    if stay:
        k, v = stay[0]
        avg = nums.get("(비교) 숙박 비중 시군구 평균")
        parts.append(f"숙박 비중 지수는 {v}" + (f"(전남·광주 시군구 평균 {avg})" if avg else "") + "입니다.")
    return " ".join(parts) + " (출처: 한국관광공사 관광빅데이터)"


def analyst_agent(state: PlanState) -> PlanState:
    p = state["parsed"]
    nums = db.evidence_numbers(p["sigungu"], p["month"])
    yyyymm = p["start_date"][:4] + p["start_date"][5:7]
    fest = db.festivals(p["sigungu"], yyyymm)
    fest_list = [{"title": r.title, "start": r.start_date, "end": r.end_date} for r in fest.itertuples()]
    # 수치 문장은 코드가 DB 값으로 직접 쓴다 (LLM이 숫자를 바꾸는 일을 원천 차단)
    facts = evidence_sentence(nums, p["month"])
    prompt = (
        "너는 관광 데이터 분석가다. 아래 사실을 보고 여행자에게 도움이 될 해석을 한 문장으로 써라. "
        "숫자는 절대 쓰지 마라(숫자는 이미 따로 보여준다).\n"
        f"혼잡 회피 희망: {p['avoid_crowd']}\n사실: {facts}\n"
        f"해당 월 축제: {', '.join(f['title'] for f in fest_list) or '없음'}"
    )
    insight = chat(0.2).invoke(prompt, config=_cfg(state, "planner.analyst")).content.strip()
    text = f"{facts}\n\n💡 {insight}"
    return {"evidence": nums, "evidence_text": text, "festivals": fest_list,
            "trace": [f"📊 데이터 분석: 방문자·체류·소비 지표 {len(nums) - 1}개, 축제 {len(fest_list)}건 확인"]}


def weather_agent(state: PlanState) -> PlanState:
    p = state["parsed"]
    s = db.sigungu_df().set_index("name").loc[p["sigungu"]]
    fc = weather.forecast(float(s.lat), float(s.lon), date.fromisoformat(p["start_date"]), p["days"])
    rainy = sum(1 for d in fc if d.get("rainy"))
    return {"weather": fc, "trace": [f"🌤️ 날씨 확인: {fc[0]['summary']}" + (f" · 비 예보 {rainy}일 → 실내 우선" if rainy else "")]}


def planner_agent(state: PlanState) -> PlanState:
    p = state["parsed"]
    per_day = {"여유": 2, "보통": 3, "알차게": 4}.get(p["pace"], 3)
    cand_txt = "\n".join(
        f"- {c['key']} | {c['title']} | {c['category']} | {'실내' if c['indoor'] else '실외'} | {c['overview'][:90]}"
        for c in state["candidates"])
    wx = "; ".join(f"{i + 1}일차 {d['summary']}" for i, d in enumerate(state.get("weather", [])))
    feedback = ""
    if state.get("issues"):
        feedback = "\n이전 일정의 문제를 반드시 고쳐라:\n- " + "\n- ".join(state["issues"])
    prompt = (
        f"너는 전남·광주 여행 일정 플래너다. {p['sigungu']} {p['days']}일 일정을 만들어라.\n"
        f"동행: {p['companion']} / 테마: {', '.join(p['themes'])} / 하루 {per_day}곳 / 혼잡 회피: {p['avoid_crowd']}\n"
        f"날씨: {wx}. 비 예보가 있는 날은 실내 장소를 우선해라.\n"
        f"지역 데이터 요약: {state.get('evidence_text', '')}\n"
        "규칙: 아래 후보 목록의 후보 번호(P01 형식)만 key 로 사용하고, 같은 장소를 두 번 넣지 마라. "
        "목록에 없는 장소·입장료·운영시간은 지어내지 마라. 모든 문장은 한국어로만 써라(영어 단어·한자 금지).\n"
        f"후보 목록:\n{cand_txt}{feedback}"
    )
    plan: Plan = _structured(Plan, 0.4).invoke(prompt, config=_cfg(state, "planner.plan"))
    n = state.get("attempts", 0) + 1
    return {"plan": plan.model_dump(), "attempts": n, "issues": [],
            "trace": [f"🗓️ 일정 작성: {len(plan.days)}일 일정 초안" + (f" (재작성 {n - 1}회차)" if n > 1 else "")]}


SLOT_ORDER = ["오전", "점심 후", "오후", "저녁"]


def order_by_slot(stops: list[dict]) -> list[dict]:
    """시간대 순서(오전→점심 후→오후→저녁)를 지키고, 같은 시간대 안에서만 가까운 순으로 정렬."""
    out: list[dict] = []
    for slot in SLOT_ORDER + [None]:
        group = [s for s in stops if (s.get("slot") == slot) or (slot is None and s.get("slot") not in SLOT_ORDER)]
        if not group:
            continue
        start = (out[-1]["lat"], out[-1]["lon"]) if out else None
        out += geo.order_route(group, start)
    return out


def route_agent(state: PlanState) -> PlanState:
    by_id = {c["key"]: c for c in state["candidates"]}
    days = []
    for d in state["plan"]["days"]:
        stops = []
        for s in d["stops"]:
            c = by_id.get(s["key"].strip().upper())
            if c:
                stops.append({**c, "reason": s["reason"], "slot": s["slot"]})
        ordered = order_by_slot(stops)
        km = geo.route_km(ordered)
        days.append({"day": d["day"], "theme": d["theme"], "stops": ordered,
                     "km": round(km, 1), "minutes": geo.drive_minutes(km)})
    total = sum(d["km"] for d in days)
    return {"days": days, "trace": [f"🗺️ 동선 정렬: 시간대 순서 + Haversine 최근접, 총 이동 약 {total:.1f}km(직선)"]}


def validator_agent(state: PlanState) -> PlanState:
    p = state["parsed"]
    cand_ids = {c["key"] for c in state["candidates"]}
    issues, seen = [], set()
    if len(state["plan"]["days"]) != p["days"]:
        issues.append(f"일수가 {p['days']}일이어야 하는데 {len(state['plan']['days'])}일이다")
    for d in state["plan"]["days"]:
        for s in d["stops"]:
            k = s["key"].strip().upper()
            if k not in cand_ids:
                issues.append(f"후보에 없는 번호 {s['key']} 사용 (P01~P{len(cand_ids):02d} 중에서만 고를 것)")
            if k in seen:
                issues.append(f"{k} 중복 방문")
            seen.add(k)
    for d in state.get("days", []):
        if len(d["stops"]) < 2:
            issues.append(f"{d['day']}일차 방문지가 2곳 미만")
        if d["km"] > 80:
            issues.append(f"{d['day']}일차 이동거리 {d['km']}km 로 너무 멀다. 가까운 곳으로 바꿔라")
    status = "통과" if not issues else f"문제 {len(issues)}건"
    return {"issues": issues, "trace": [f"✅ DB 검증: {status}"]}


def after_validate(state: PlanState) -> str:
    if not state.get("issues"):
        return "finalize"
    return "planner" if state.get("attempts", 0) < MAX_ATTEMPTS else "repair"


def repair_agent(state: PlanState) -> PlanState:
    """재작성 한도를 넘긴 문제는 규칙으로 고친다: 잘못된 장소 제거 → 가까운 미사용 후보로 채움."""
    p = state["parsed"]
    per_day = {"여유": 2, "보통": 3, "알차게": 4}.get(p["pace"], 3)
    days = state.get("days", [])[: p["days"]]
    while len(days) < p["days"]:
        days.append({"day": len(days) + 1, "theme": "추가 일정", "stops": []})
    used: set[str] = set()
    removed = added = 0
    for d in days:
        keep = []
        for s in d["stops"]:
            if s["key"] in used:
                removed += 1
                continue
            used.add(s["key"])
            keep.append(s)
        d["stops"] = keep
    for d in days:
        # 너무 먼 날은 첫 장소에서 가장 먼 곳부터 뺀다
        while len(d["stops"]) > 2 and geo.route_km(geo.order_route(d["stops"])) > 80:
            first = d["stops"][0]
            far = max(d["stops"][1:], key=lambda s: geo.haversine(first["lat"], first["lon"], s["lat"], s["lon"]))
            d["stops"].remove(far)
            removed += 1
        while len(d["stops"]) < min(per_day, 2):
            pool = [c for c in state["candidates"] if c["key"] not in used]
            if not pool:
                break
            anchor = d["stops"][-1] if d["stops"] else pool[0]
            nxt = min(pool, key=lambda c: geo.haversine(anchor["lat"], anchor["lon"], c["lat"], c["lon"]))
            d["stops"].append({**nxt, "reason": "가까운 동선을 위해 자동으로 보완한 장소", "slot": "오후"})
            used.add(nxt["key"])
            added += 1
        d["stops"] = order_by_slot(d["stops"])
        d["km"] = round(geo.route_km(d["stops"]), 1)
        d["minutes"] = geo.drive_minutes(d["km"])
    return {"days": days, "issues": [],
            "trace": [f"🔧 자동 보정: 중복·오류 {removed}건 제거, 근처 후보 {added}곳 보충"]}


def finalize(state: PlanState) -> PlanState:
    """각 날 마지막 방문지 근처(5km)의 음식점·숙박 후보를 DB에서 붙인다."""
    p = state["parsed"]
    food = db.places(p["sigungu"], ("39",))
    stay = db.places(p["sigungu"], ("32",))
    for d in state["days"]:
        if not d["stops"]:
            continue
        last = d["stops"][-1]

        def near(df, n=2):
            if df.empty:
                return []
            dist = df.apply(lambda r: geo.haversine(last["lat"], last["lon"], r.lat, r.lon), axis=1)
            df2 = df.assign(km=dist).query("km <= 5").nsmallest(n, "km")
            return [{"title": r.title, "km": round(r.km, 1), "category": r.cat3} for r in df2.itertuples()]
        d["food"], d["stay"] = near(food), near(stay)
    left = state.get("issues") or []
    msg = "📝 마무리: 주변 음식점·숙박 후보 연결" + (f" (남은 문제 {len(left)}건 표시)" if left else "")
    return {"days": state["days"], "trace": [msg]}


def stop_on_error(state: PlanState) -> str:
    return "end" if state.get("error") else "scout"


# ---------------------------------------------------------------- 그래프
def build_graph():
    from langgraph.graph import END, START, StateGraph
    g = StateGraph(PlanState)
    for name, fn in [("intake", intake_agent), ("scout", scout_agent), ("analyst", analyst_agent),
                     ("weather", weather_agent), ("planner", planner_agent), ("route", route_agent),
                     ("validator", validator_agent), ("repair", repair_agent), ("finalize", finalize)]:
        g.add_node(name, fn)
    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", stop_on_error, {"scout": "scout", "end": END})
    g.add_edge("scout", "analyst")          # 병렬 분기
    g.add_edge("scout", "weather")
    g.add_edge(["analyst", "weather"], "planner")   # 두 에이전트가 끝나면 합류
    g.add_edge("planner", "route")
    g.add_edge("route", "validator")
    g.add_conditional_edges("validator", after_validate,
                            {"planner": "planner", "repair": "repair", "finalize": "finalize"})
    g.add_edge("repair", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


_GRAPH = None


def run(request: str, form: dict | None = None, on_step=None) -> PlanState:
    """on_step(node_name, partial_state) 로 진행 상황을 화면에 흘려보낼 수 있다."""
    global _GRAPH
    _GRAPH = _GRAPH or build_graph()
    state: PlanState = {"request": request, "form": form or {}, "attempts": 0, "trace": []}
    final: dict = dict(state)
    for chunk in _GRAPH.stream(state, stream_mode="updates"):
        for node, upd in chunk.items():
            if not upd:
                continue
            for k, v in upd.items():
                final[k] = final.get(k, []) + v if k == "trace" else v
            if on_step:
                on_step(node, upd)
    return final


def mermaid() -> str:
    global _GRAPH
    _GRAPH = _GRAPH or build_graph()
    return _GRAPH.get_graph().draw_mermaid()
