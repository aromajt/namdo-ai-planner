import hmac

import plotly.express as px
import streamlit as st

from core import applog, db
from core.config import DATA, secret
from core.ui import setup_page

setup_page("관리자", eyebrow="NAMDO-ON · OPERATIONS", sub="AI 사용량·비용·응답시간, 데이터 갱신 작업, 사용자 의견을 확인합니다")

# ---- 로그인 (비밀번호는 secrets 에만 저장, 비교는 hmac 으로 타이밍 공격 방지)
if not st.session_state.get("admin"):
    pw = st.text_input("관리자 비밀번호", type="password")
    if st.button("로그인"):
        expected = secret("ADMIN_PASSWORD") or ""
        if expected and hmac.compare_digest(pw.encode(), expected.encode()):
            st.session_state.admin = True
            st.rerun()
        st.error("비밀번호가 올바르지 않습니다.")
        applog.log.warning("관리자 로그인 실패")
    st.stop()

if st.sidebar.button("로그아웃"):
    st.session_state.admin = False
    st.rerun()

calls = applog.read_table("llm_calls")
tab1, tab2, tab3, tab4 = st.tabs(["📈 AI 사용량", "🔄 데이터 갱신", "💬 의견·즐겨찾기", "🧩 시스템"])

with tab1:
    if calls.empty:
        st.info("아직 AI 호출 기록이 없습니다.")
    else:
        c = st.columns(5)
        c[0].metric("AI 호출", f"{len(calls):,}회")
        c[1].metric("토큰", f"{int(calls.prompt_tokens.sum() + calls.completion_tokens.sum()):,}")
        c[2].metric("추정 비용", f"${calls.cost_usd.sum():.4f}")
        ok = calls[calls.ok == 1]
        c[3].metric("평균 응답", f"{ok.latency_ms.mean() / 1000:.1f}초" if not ok.empty else "-")
        c[4].metric("오류율", f"{(1 - calls.ok.mean()) * 100:.1f}%")
        calls["date"] = calls.ts.str[:10]
        a, b = st.columns(2)
        by = calls.groupby(["feature", "provider"]).size().reset_index(name="호출")
        a.plotly_chart(px.bar(by, x="feature", y="호출", color="provider", height=320,
                              title="기능별 호출", color_discrete_sequence=["#14897A", "#E07A2E"]),
                       use_container_width=True)
        b.plotly_chart(px.box(ok, x="feature", y="latency_ms", height=320, title="기능별 응답시간(ms)",
                              color_discrete_sequence=["#14897A"]), use_container_width=True)
        st.dataframe(calls[["ts", "feature", "provider", "model", "prompt_tokens", "completion_tokens",
                            "latency_ms", "ok", "error", "question"]].head(200), use_container_width=True,
                     hide_index=True)

with tab2:
    m = db.meta()
    st.markdown(f"- DB 빌드: **{m['built_at']}** · 관광 콘텐츠 {m['places']}건 · 소개글 {m['overview_filled']}건 · "
                f"축제 {m['festivals']}건 · 방문자 자료 {m['visitors_range']}")
    st.markdown("- 자동 갱신: `python -m scripts.scheduler` (매일 06:00 수집 → DB → 인덱스). "
                "소개글은 상세 API 일일 한도(1,000건) 안에서 매일 이어받습니다.")
    st.dataframe(applog.read_table("jobs"), use_container_width=True, hide_index=True)

with tab3:
    fb = applog.read_table("feedback")
    if not fb.empty:
        st.metric("만족도(👍 비율)", f"{(fb.rating > 0).mean() * 100:.0f}%", help=f"{len(fb)}건")
    st.dataframe(fb, use_container_width=True, hide_index=True)
    st.markdown("##### 인기 즐겨찾기")
    fav = applog.read_table("favorites")
    if not fav.empty:
        st.dataframe(fav.groupby("title").size().sort_values(ascending=False).rename("담은 수").head(15))

with tab4:
    log_file = DATA / "service.log"
    if log_file.exists():
        lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()[-60:]
        st.code("\n".join(lines), language="log")
    from core import planner
    with st.expander("LangGraph 플래너 구조 (mermaid)"):
        st.code(planner.mermaid(), language="mermaid")
