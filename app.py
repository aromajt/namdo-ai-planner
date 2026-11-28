"""남도ON AI 여행 플래너 — Streamlit 진입점.

실행: streamlit run app.py
"""
import importlib
import sys
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="남도ON AI 여행 플래너", page_icon="🌿", layout="wide")


def _git_head() -> str:
    """서버에 받아진 코드의 커밋 (git 명령 없이 .git 파일을 직접 읽음)."""
    g = Path(__file__).resolve().parent / ".git"
    try:
        head = (g / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head
        ref = head.split(" ", 1)[1]
        if (g / ref).exists():
            return (g / ref).read_text(encoding="utf-8").strip()
        for line in (g / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line.split(" ", 1)[0]
    except Exception:
        pass
    return ""


# Streamlit Cloud 는 푸시를 받으면 app.py 만 다시 실행하고 이미 불러온 core 모듈은 그대로 둔다.
# 커밋이 바뀌었으면 core 모듈을 의존 순서대로 다시 읽어, 재부팅 없이 새 코드가 반영되게 한다.
_CORE_ORDER = ["config", "applog", "db", "geo", "weather", "llm", "retriever",
               "planner", "chat_agent", "vision", "media", "ui"]
_head = _git_head()
if getattr(sys, "_namdo_loaded_commit", None) != _head:
    for _name in _CORE_ORDER:
        _mod = sys.modules.get(f"core.{_name}")
        if _mod is not None:
            importlib.reload(_mod)
    sys._namdo_loaded_commit = _head

from core.ui import provider_selector, version_caption  # noqa: E402

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
nav = st.navigation(pages)
version_caption()
nav.run()
