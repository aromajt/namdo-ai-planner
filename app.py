"""남도ON AI 여행 플래너 — Streamlit 진입점.

실행: streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="남도ON AI 여행 플래너", page_icon="🌿", layout="wide")

from core.ui import provider_selector  # noqa: E402  (set_page_config 이후 import)

pages = {
    "서비스": [
        st.Page("views/home.py", title="홈", icon="🏠", default=True),
        st.Page("views/explore.py", title="관광지 탐색", icon="🗺️"),
        st.Page("views/planner.py", title="AI 여행 추천", icon="🧭"),
        st.Page("views/chatbot.py", title="관광 안내 챗봇", icon="💬"),
        st.Page("views/photo.py", title="사진으로 찾기", icon="📷"),
    ],
    "운영": [
        st.Page("views/admin.py", title="관리자", icon="🛠️"),
        st.Page("views/about.py", title="데이터·AI 윤리", icon="📚"),
    ],
}

st.sidebar.markdown("## 🌿 남도ON AI")
st.sidebar.caption("데이터로 근거를 대고, AI로 계획하는 남도 여행")
provider_selector()
st.navigation(pages).run()
