"""공통 설정: 경로, 비밀값, 모델 선택.

비밀값은 코드에 적지 않는다. 우선순위: 환경변수 → .streamlit/secrets.toml
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 이 파이썬 프로세스가 시작된 시각 (배포 앱이 실제로 재시작됐는지 확인용)
import datetime as _dt
PROCESS_STARTED = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=9))).strftime("%m-%d %H:%M")
DATA = ROOT / "data"
RAW = DATA / "raw"
TOUR_DB = DATA / "tour.db"          # 관광 원천 데이터 (읽기 위주)
APP_DB = DATA / "app.db"            # 서비스 로그·사용자·캐시 (쓰기)
INDEX_DIR = DATA / "index"          # 텍스트 벡터 인덱스 (FAISS)
CLIP_DIR = DATA / "clip"            # 이미지 임베딩 (로컬 전용)
DOCS_DIR = DATA / "docs"            # RAG 문서(홍보물 PDF 등)

for d in (DATA, RAW, INDEX_DIR, CLIP_DIR, DOCS_DIR):
    d.mkdir(parents=True, exist_ok=True)

_SECRETS_FILE = ROOT / ".streamlit" / "secrets.toml"


def _file_secrets() -> dict:
    try:
        with open(_SECRETS_FILE, "rb") as f:
            return tomllib.load(f)
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return {}


def secret(name: str, default: str | None = None) -> str | None:
    """프로젝트 secrets.toml → 환경변수 → Streamlit Cloud st.secrets 순서로 찾는다.

    프로젝트 파일을 먼저 보는 이유: PC 전역 환경변수에 다른 용도의 값이 있어도
    이 프로젝트에 넣은 키가 우선하도록.
    """
    val = _file_secrets().get(name)
    if val and "..." not in str(val):
        return val
    if os.getenv(name):
        return os.getenv(name)
    try:  # Streamlit Cloud 에서는 st.secrets 로만 들어온다
        import streamlit as st
        return st.secrets.get(name, default)
    except Exception:
        return default


# ---- 모델 설정 ---------------------------------------------------------
# provider: "openai"(클라우드·기본) | "ollama"(로컬 PC, 비용 0, 외부 전송 없음)
PROVIDER = os.getenv("NAMDO_PROVIDER", "openai")
OPENAI_CHAT_MODEL = "gpt-4o-mini"
OPENAI_EMBED_MODEL = "text-embedding-3-small"
OPENAI_TTS_MODEL = "tts-1"
OLLAMA_CHAT_MODEL = "qwen3.5:9b"
OLLAMA_EMBED_MODEL = "bge-m3"

# 안전장치
MAX_INPUT_CHARS = 500         # 사용자 입력 길이 제한
LLM_TIMEOUT = 60              # 초
LLM_MAX_RETRIES = 2

REGIONS = {"전남": "38", "광주": "5"}   # TourAPI areaCode
CONTENT_TYPES = {
    "12": "관광지", "14": "문화시설", "15": "축제공연행사", "25": "여행코스",
    "28": "레포츠", "32": "숙박", "38": "쇼핑", "39": "음식점",
}
# 일정 추천에 쓰는 '방문지' 유형 (숙박·음식점은 따로 제안)
VISIT_TYPES = ("12", "14", "28", "38")
