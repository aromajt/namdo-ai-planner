import plotly.express as px
import streamlit as st

from core import applog, db
from core.ui import esc, places_map, session_id, setup_page

setup_page("관광지 탐색", sub="시군구·유형·키워드로 찾고, 지역의 방문 추이를 함께 봅니다")

sg = db.sigungu_df()
c1, c2, c3 = st.columns([1.2, 1.6, 1.2])
region = c1.selectbox("권역", ["전체", "전남", "광주"])
names = sg[sg.region == region].name.tolist() if region != "전체" else sg.name.tolist()
sigungu = c1.selectbox("시군구", ["전체"] + names)
types = c2.multiselect("유형", ["관광지", "문화시설", "레포츠", "쇼핑", "음식점", "숙박", "축제공연행사"],
                       default=["관광지", "문화시설"])
kw = c3.text_input("키워드", placeholder="예: 해수욕장, 사찰, 정원")


@st.cache_data(ttl=600)
def load(sigungu, region, types, kw):
    df = db.places(None if sigungu == "전체" else sigungu, keyword=kw or None)
    if region != "전체":
        df = df[df.region == region]
    if types:
        df = df[df.type_name.isin(types)]
    return df


df = load(sigungu, region, tuple(types), kw.strip()[:30])
st.caption(f"검색 결과 {len(df):,}곳")
tab_map, tab_list, tab_trend = st.tabs(["🗺️ 지도", "📋 목록", "📈 방문 추이"])

with tab_map:
    places_map(df.head(1500))
    if len(df) > 1500:
        st.caption("지도에는 1,500곳까지 표시합니다. 조건을 좁혀 보세요.")

with tab_list:
    sid = session_id()
    favs = {c for c, _ in applog.favorites(sid)}
    for r in df.head(40).itertuples():
        a, b = st.columns([1, 4])
        if r.thumb:
            a.image(r.thumb, use_container_width=True)
        b.markdown(f"**{esc(r.title)}** · <span class='namdo-badge'>{esc(r.type_name)} · {esc(r.cat3)}</span>"
                   f"<br><small>{esc(r.addr)}</small>", unsafe_allow_html=True)
        if r.overview:
            b.caption(r.overview[:160] + ("…" if len(r.overview) > 160 else ""))
        if b.button("★ 즐겨찾기 해제" if r.contentid in favs else "☆ 즐겨찾기", key=f"fav{r.contentid}"):
            applog.toggle_favorite(sid, r.contentid, r.title)
            st.rerun()
    if favs:
        st.markdown("##### 내 즐겨찾기")
        st.write(", ".join(t for _, t in applog.favorites(sid)))

with tab_trend:
    target = sigungu if sigungu != "전체" else st.selectbox("방문 추이를 볼 시군구", names)
    vp = db.visitor_profile(target)
    if vp.empty:
        st.info("방문자 자료가 없습니다.")
    else:
        long = vp.melt(id_vars="ym", value_vars=["local_daily", "outsider_daily", "foreigner_daily"],
                       var_name="구분", value_name="일평균 추정 방문")
        long["구분"] = long["구분"].map({"local_daily": "현지인", "outsider_daily": "외지인",
                                       "foreigner_daily": "외국인"})
        long["월"] = long.ym.str[:4] + "." + long.ym.str[4:]
        fig = px.line(long, x="월", y="일평균 추정 방문", color="구분", markers=True, height=360,
                      color_discrete_sequence=["#9DB8B1", "#14897A", "#E07A2E"])
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), legend_title_text="")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("이동통신 기반 추정 방문자(한국관광공사 관광빅데이터)의 월 일평균입니다. 실제 인원 수와 다를 수 있습니다.")
        ev = db.evidence_numbers(target)
        st.json({k: v for k, v in ev.items() if not k.startswith("(비교)")}, expanded=False)
