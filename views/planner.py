from datetime import date, timedelta

import streamlit as st

from core import applog, db, media, planner
from core.llm import openai_ok
from core.ui import esc, place_card, route_map, setup_page

setup_page("AI 여행 추천", sub="에이전트 7개가 조건 해석 → 후보 탐색 → 데이터·날씨 분석 → 일정 작성 → 동선 정렬 → DB 검증 순서로 협업합니다")

names = db.sigungu_names()
with st.form("plan_form"):
    c1, c2, c3, c4 = st.columns(4)
    sigungu = c1.selectbox("지역", names, index=names.index("여수시") if "여수시" in names else 0)
    days = c2.selectbox("기간", [1, 2, 3], index=1, format_func=lambda d: "당일" if d == 1 else f"{d - 1}박 {d}일")
    companion = c3.selectbox("동행", ["가족(아이)", "부모님", "연인", "친구", "혼자"])
    start = c4.date_input("출발일", date.today() + timedelta(days=3))
    themes = st.multiselect("테마", ["바다", "자연·산책", "역사·문화", "체험", "사진 명소", "야경", "힐링"],
                            default=["바다", "자연·산책"])
    c5, c6 = st.columns([1, 3])
    pace = c5.radio("일정 강도", ["여유", "보통", "알차게"], index=1, horizontal=True)
    avoid = c5.checkbox("붐비는 곳은 피하고 싶어요")
    extra = c6.text_area("하고 싶은 말 (선택)", max_chars=300,
                         placeholder="예: 부모님 무릎이 안 좋아서 많이 걷지 않는 코스면 좋겠어요")
    go = st.form_submit_button("AI 여행 일정 추천 받기", type="primary", use_container_width=True)

if go:
    form = {"sigungu": sigungu, "days": days, "companion": companion, "themes": themes,
            "pace": pace, "avoid_crowd": avoid, "start_date": start.isoformat()}
    request = f"{sigungu} {days}일 {companion} 여행, 테마 {', '.join(themes)}, {pace}." + \
              (" 붐비지 않는 곳 위주." if avoid else "") + (f" {extra}" if extra else "")
    with st.status("에이전트들이 일정을 만들고 있어요…", expanded=True) as status:
        def on_step(node, upd):
            for t in upd.get("trace", []):
                st.markdown(f'<div class="namdo-trace">{esc(t)}</div>', unsafe_allow_html=True)
        try:
            result = planner.run(request, form, on_step=on_step)
            status.update(label="일정 완성!", state="complete", expanded=False)
            st.session_state.plan_result = result
            st.session_state.pop("plan_audio", None)
        except Exception as e:
            applog.log.exception("planner 실패")
            status.update(label="일정 생성 실패", state="error")
            st.error(f"일정을 만들지 못했습니다. 잠시 후 다시 시도해 주세요. ({type(e).__name__})")

res = st.session_state.get("plan_result")
if res:
    if res.get("error"):
        st.warning(res["error"])
        st.stop()
    plan = res["plan"]
    st.subheader(plan["title"])
    st.write(plan["summary"])
    if res.get("issues"):
        st.warning("검증에서 남은 문제: " + " / ".join(res["issues"]))

    left, right = st.columns([3, 2])
    with left:
        route_map(res["days"])
    with right:
        st.markdown("##### 📊 이 일정의 데이터 근거")
        st.info(res.get("evidence_text", ""))
        with st.expander("근거 수치 원본 (DB 조회값)"):
            st.json(res.get("evidence", {}))
        if res.get("festivals"):
            st.markdown("##### 🎉 여행 기간 축제")
            for f in res["festivals"]:
                st.markdown(f"- {esc(f['title'])} ({f['start']}~{f['end']})")
        st.markdown("##### 🌤️ 날씨")
        for i, w in enumerate(res.get("weather", []), 1):
            t = f" {w['tmin']:.0f}~{w['tmax']:.0f}℃ · 강수확률 {w['rain_prob']}%" if "tmax" in w else ""
            st.markdown(f"- {i}일차 {w['date']}: {w['summary']}{t}")

    for d in res["days"]:
        st.markdown(f"### {d['day']}일차 · {esc(d['theme'])}")
        st.caption(f"이동 약 {d['km']}km(직선) · 차량 약 {d['minutes']}분 (어림값)")
        cols = st.columns(max(len(d["stops"]), 1))
        for i, (col, s) in enumerate(zip(cols, d["stops"]), 1):
            with col:
                place_card(f"{i}. {s['title']}", s["category"], s["reason"], s.get("image", ""), s["slot"])
        extra = []
        if d.get("food"):
            extra.append("🍽️ 근처 음식점: " + ", ".join(f"{f['title']}({f['km']}km)" for f in d["food"]))
        if d.get("stay"):
            extra.append("🛏️ 근처 숙박: " + ", ".join(f"{f['title']}({f['km']}km)" for f in d["stay"]))
        if extra:
            st.caption("  ·  ".join(extra) + "  — TourAPI 등록 정보, 영업 여부는 확인 필요")

    if plan.get("tips"):
        st.markdown("##### 💡 여행 팁")
        for t in plan["tips"]:
            st.markdown(f"- {esc(t)}")

    st.divider()
    text = media.plan_to_text(res)
    a, b, c = st.columns(3)
    a.download_button("📄 일정 텍스트 저장", text, file_name="namdo_plan.txt", use_container_width=True)
    if openai_ok():
        if b.button("🔊 음성 안내 만들기", use_container_width=True):
            with st.spinner("음성 생성 중…"):
                st.session_state.plan_audio = media.tts(text)
        if st.session_state.get("plan_audio"):
            st.audio(st.session_state.plan_audio, format="audio/mp3")
    else:
        b.button("🔊 음성 안내 (OpenAI 키 필요)", disabled=True, use_container_width=True)
    lang = c.selectbox("다국어 안내", ["선택", "English", "日本語", "中文"], label_visibility="collapsed")
    if lang != "선택":
        with st.spinner(f"{lang} 번역 중…"):
            st.text_area(lang, media.translate(text, lang), height=220)

    with st.expander("🤖 에이전트 활동 기록"):
        for t in res.get("trace", []):
            st.markdown(f'<div class="namdo-trace">{esc(t)}</div>', unsafe_allow_html=True)
    fb1, fb2, _ = st.columns([1, 1, 4])
    if fb1.button("👍 좋아요"):
        applog.add_feedback("planner", 1, plan["title"])
        st.toast("의견 감사합니다!")
    if fb2.button("👎 아쉬워요"):
        applog.add_feedback("planner", -1, plan["title"])
        st.toast("더 나아지도록 반영하겠습니다.")
