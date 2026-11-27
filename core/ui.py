"""화면 공통 요소: 스타일, 카드, 지도, 세션 ID, 모델 선택."""
from __future__ import annotations

import html
import os
import uuid

import folium
import streamlit as st
from folium.plugins import MarkerCluster

CSS = """
<style>
.block-container{padding-top:2.2rem;max-width:1200px}
.namdo-eyebrow{color:#14897A;font-weight:700;letter-spacing:.06em;font-size:.8rem}
.namdo-card{background:#fff;border:1px solid #DCEBE7;border-radius:16px;padding:14px 16px;
  box-shadow:0 2px 6px rgba(20,50,60,.06);height:100%}
.namdo-card h4{margin:.2rem 0 .3rem;font-size:1.05rem;color:#16323D}
.namdo-card .cat{color:#14897A;font-size:.8rem;font-weight:600}
.namdo-card .why{color:#45606A;font-size:.88rem;line-height:1.45}
.namdo-card img{width:100%;height:150px;object-fit:cover;border-radius:12px;margin-bottom:8px}
.namdo-noimg{width:100%;height:150px;border-radius:12px;margin-bottom:8px;background:#E6F4F1;
  display:flex;align-items:center;justify-content:center;color:#7FA79E;font-size:.85rem}
.namdo-trace{font-size:.9rem;color:#2C4A54;line-height:1.7}
.namdo-badge{display:inline-block;background:#E6F4F1;color:#0F6E62;border-radius:999px;
  padding:2px 10px;font-size:.78rem;margin:2px 4px 2px 0}
</style>
"""


def setup_page(title: str, eyebrow: str = "NAMDO-ON · AI TRAVEL PLANNER", sub: str = "") -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(f'<div class="namdo-eyebrow">{eyebrow}</div>', unsafe_allow_html=True)
    st.title(title)
    if sub:
        st.caption(sub)


def session_id() -> str:
    if "sid" not in st.session_state:
        st.session_state.sid = uuid.uuid4().hex[:12]
    return st.session_state.sid


def esc(s) -> str:
    return html.escape(str(s or ""))


def place_card(title: str, category: str = "", body: str = "", image: str = "", badge: str = "") -> None:
    img = (f'<img src="{esc(image)}" alt="{esc(title)}">' if image
           else '<div class="namdo-noimg">사진 없음</div>')
    b = f'<span class="namdo-badge">{esc(badge)}</span>' if badge else ""
    st.markdown(f'<div class="namdo-card">{img}<div class="cat">{esc(category)}</div>'
                f'<h4>{esc(title)}</h4>{b}<div class="why">{esc(body)}</div></div>',
                unsafe_allow_html=True)


DAY_COLORS = ["#14897A", "#E07A2E", "#3B6FB6", "#9B4F96"]


def route_map(days: list[dict], height: int = 430):
    from streamlit_folium import st_folium
    pts = [(s["lat"], s["lon"]) for d in days for s in d["stops"]]
    if not pts:
        return
    m = folium.Map(location=[sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)],
                   zoom_start=11, tiles="OpenStreetMap")
    for d in days:
        color = DAY_COLORS[(d["day"] - 1) % len(DAY_COLORS)]
        line = [(s["lat"], s["lon"]) for s in d["stops"]]
        if len(line) > 1:
            folium.PolyLine(line, color=color, weight=4, opacity=.8, tooltip=f"{d['day']}일차").add_to(m)
        for i, s in enumerate(d["stops"], 1):
            folium.Marker(
                (s["lat"], s["lon"]), tooltip=f"{d['day']}일차 {i}. {s['title']}",
                icon=folium.DivIcon(html=f'<div style="background:{color};color:#fff;border-radius:50%;'
                                         f'width:26px;height:26px;text-align:center;line-height:26px;'
                                         f'font-weight:700;border:2px solid #fff">{i}</div>')).add_to(m)
    m.fit_bounds([[min(p[0] for p in pts), min(p[1] for p in pts)],
                  [max(p[0] for p in pts), max(p[1] for p in pts)]])
    st_folium(m, height=height, use_container_width=True, returned_objects=[])


def places_map(df, height: int = 480):
    from streamlit_folium import st_folium
    if df.empty:
        st.info("지도에 표시할 장소가 없습니다.")
        return
    m = folium.Map(location=[df.lat.mean(), df.lon.mean()], zoom_start=9, tiles="OpenStreetMap")
    cluster = MarkerCluster().add_to(m)
    for r in df.itertuples():
        pop = f"<b>{esc(r.title)}</b><br>{esc(r.type_name)} · {esc(r.cat3)}<br>{esc(r.addr)}"
        if r.thumb:
            pop = f'<img src="{esc(r.thumb)}" width="180"><br>' + pop
        folium.Marker((r.lat, r.lon), tooltip=r.title, popup=folium.Popup(pop, max_width=220)).add_to(cluster)
    st_folium(m, height=height, use_container_width=True, returned_objects=[])


@st.cache_data(ttl=60)
def ollama_alive() -> bool:
    import requests
    try:
        return requests.get("http://localhost:11434/api/tags", timeout=0.5).ok
    except Exception:
        return False


def provider_selector() -> str:
    """사이드바: OpenAI(클라우드) ↔ Ollama(로컬) 모델 전환."""
    from core.llm import openai_ok
    opts = []
    if openai_ok():
        opts.append("openai")
    if ollama_alive():
        opts.append("ollama")
    if not opts:
        st.sidebar.error("사용 가능한 AI 모델이 없습니다 (OpenAI 키 또는 로컬 Ollama 필요)")
        return "none"
    labels = {"openai": "☁️ OpenAI gpt-4o-mini", "ollama": "🖥️ 로컬 qwen3.5 (Ollama)"}
    cur = os.getenv("NAMDO_PROVIDER", opts[0])
    choice = st.sidebar.radio("AI 모델", opts, index=opts.index(cur) if cur in opts else 0,
                              format_func=labels.get, key="provider")
    os.environ["NAMDO_PROVIDER"] = choice
    return choice
