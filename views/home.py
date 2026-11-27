import plotly.express as px
import streamlit as st

from core import db
from core.ui import setup_page

setup_page("남도ON AI 여행 플래너",
           sub="전남광주통합특별시 공공 관광데이터 + LangGraph 멀티에이전트로 만드는 '근거 있는' 여행 일정")

meta = db.meta()
c = st.columns(4)
c[0].metric("관광 콘텐츠", f"{int(meta['places']):,}건")
c[1].metric("소개글 확보", f"{int(meta['overview_filled']):,}건", help="상세정보 API 일일 한도로 매일 자동 보강")
c[2].metric("축제·행사", f"{int(meta['festivals'])}건")
c[3].metric("시군구", f"{len(db.sigungu_names())}곳")

st.markdown("#### 무엇을 할 수 있나요?")
cols = st.columns(4)
items = [("🧭 AI 여행 추천", "지역·기간·동행만 고르면 에이전트들이 데이터를 근거로 일정을 짜고 DB로 검증합니다.",
          "views/planner.py"),
         ("💬 관광 안내 챗봇", "홍보물·관광지 소개를 검색해 출처와 함께 답합니다. 대화 내용을 기억합니다.",
          "views/chatbot.py"),
         ("📷 사진으로 찾기", "마음에 드는 풍경 사진을 올리면 비슷한 남도 관광지를 찾아 드립니다.",
          "views/photo.py"),
         ("🗺️ 관광지 탐색", "3,700여 곳을 지도·유형·키워드로 찾고 지역별 방문 추이를 봅니다.",
          "views/explore.py")]
for col, (t, d, page) in zip(cols, items):
    with col:
        st.markdown(f'<div class="namdo-card"><h4>{t}</h4><div class="why">{d}</div></div>',
                    unsafe_allow_html=True)
        st.page_link(page, label="바로 가기 →")

st.markdown("#### 시군구별 관광 콘텐츠")
cnt = db.query("SELECT sigungu_name 시군구, region 권역, type_name 유형, count(*) 개수 "
               "FROM places GROUP BY 1,2,3")
fig = px.bar(cnt, x="시군구", y="개수", color="유형", height=380,
             color_discrete_sequence=px.colors.qualitative.Safe)
fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), xaxis={"categoryorder": "total descending"},
                  legend_title_text="")
st.plotly_chart(fig, use_container_width=True)
st.caption(f"출처: {meta['source']} · 수집 {meta['places_collected_at'][:10]} · DB 빌드 {meta['built_at'][:16]}")
