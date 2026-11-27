import streamlit as st

from core import applog, chat_agent
from core.ui import session_id, setup_page

setup_page("관광 안내 챗봇", sub="에이전트가 질문에 맞는 도구(문서 검색·DB 조회·축제·날씨·거리)를 골라 답하고, 출처를 밝힙니다")

TOOL_LABEL = {"search_tourism_info": "📚 문서 검색", "find_places": "🗂️ DB 조회", "festival_schedule": "🎉 축제",
              "region_stats": "📊 방문 통계", "weather_forecast": "🌤️ 날씨", "distance_between": "📏 거리"}

if "chat" not in st.session_state:
    st.session_state.chat = [{"role": "assistant", "content":
                              "안녕하세요, 남도ON 관광 안내원입니다. 전남·광주 여행에 대해 무엇이든 물어보세요!"}]

c1, c2 = st.columns([5, 1])
with c2:
    if st.button("새 대화", use_container_width=True):
        st.session_state.chat = st.session_state.chat[:1]
        st.session_state.thread = session_id() + "-" + str(len(st.session_state.get("threads", [])) + 1)
        st.session_state.setdefault("threads", []).append(st.session_state.thread)
        st.rerun()
thread = st.session_state.get("thread", session_id())

examples = ["담양에서 대나무 숲 말고 걸을 만한 곳 있어?", "여수는 몇 월이 제일 한산해?",
            "12월에 열리는 축제 알려줘", "순천만습지에서 순천만국가정원까지 얼마나 걸려?"]
cols = st.columns(len(examples))
clicked = None
for col, ex in zip(cols, examples):
    if col.button(ex, use_container_width=True):
        clicked = ex

for m in st.session_state.chat:
    with st.chat_message(m["role"], avatar="🌿" if m["role"] == "assistant" else None):
        st.markdown(m["content"])
        if m.get("tools"):
            st.caption("사용한 도구: " + " · ".join(TOOL_LABEL.get(t, t) for t in m["tools"]))

q = st.chat_input("예: 목포에서 비 오는 날 갈 만한 실내 명소는?") or clicked
if q:
    st.session_state.chat.append({"role": "user", "content": q})
    with st.chat_message("user"):
        st.markdown(q)
    with st.chat_message("assistant", avatar="🌿"):
        with st.spinner("자료를 찾는 중…"):
            try:
                r = chat_agent.ask(q, thread)
            except Exception as e:
                applog.log.exception("chatbot 실패")
                r = {"answer": f"죄송해요, 지금은 답을 드리기 어렵습니다. 잠시 후 다시 시도해 주세요. ({type(e).__name__})",
                     "tools": []}
        st.markdown(r["answer"])
        if r["tools"]:
            st.caption("사용한 도구: " + " · ".join(TOOL_LABEL.get(t, t) for t in r["tools"]))
    st.session_state.chat.append({"role": "assistant", "content": r["answer"], "tools": r["tools"]})
