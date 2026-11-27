import streamlit as st
from PIL import Image

from core import applog, db, vision
from core.ui import place_card, setup_page

setup_page("사진으로 찾기", sub="풍경 사진을 올리면 비슷한 남도 관광지를 찾아 드립니다. 사진은 저장하지 않습니다")

modes = ["AI 비전 (사진 설명 → 검색)"]
if vision.clip_available():
    modes.append("CLIP 이미지 유사도 (로컬 GPU)")
c1, c2 = st.columns([2, 1])
mode = c1.radio("방법", modes, horizontal=True)
sigungu = c2.selectbox("지역 제한 (선택)", ["전체"] + db.sigungu_names())
src = st.file_uploader("사진 올리기 (jpg·png, 10MB 이하)", type=["jpg", "jpeg", "png"])
text_q = ""
if mode.startswith("CLIP"):
    text_q = st.text_input("또는 영어 문장으로 찾기 (CLIP 텍스트→이미지)", placeholder="e.g. bamboo forest path")

if src or text_q:
    img = Image.open(src) if src else None
    if img:
        st.image(img, width=320, caption="올린 사진 (서버에 저장하지 않음)")
    sgg = None if sigungu == "전체" else sigungu
    with st.spinner("비슷한 관광지를 찾는 중…"):
        try:
            if mode.startswith("CLIP"):
                results = vision.clip_search(img=img, text=None if img else text_q, k=6, sigungu=sgg)
                info = None
            else:
                info = vision.describe(img)
                results = vision.search_by_description(info, sgg, k=6)
        except Exception as e:
            applog.log.exception("photo 실패")
            st.error(f"분석에 실패했습니다. ({type(e).__name__})")
            st.stop()
    if info:
        st.markdown(f"**AI가 본 장면:** {info.get('scene', '')}")
        st.markdown(" ".join(f'<span class="namdo-badge">#{t}</span>' for t in info.get("tags", [])) +
                    f' <span class="namdo-badge">{info.get("type", "")}</span>', unsafe_allow_html=True)
    if not results:
        st.info("비슷한 관광지를 찾지 못했습니다. 지역 제한을 풀어 보세요.")
    cols = st.columns(3)
    for i, r in enumerate(results):
        with cols[i % 3]:
            badge = f"유사도 {r['similarity']:.2f}" if "similarity" in r else r.get("sigungu_name", "")
            place_card(r["title"], f"{r['sigungu_name']} · {r.get('cat3', '')}",
                       (r.get("overview") or r.get("addr", ""))[:110], r.get("thumb") or r.get("image", ""), badge)
            st.write("")
