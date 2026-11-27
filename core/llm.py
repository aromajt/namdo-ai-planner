"""LLM·임베딩 생성기 + 사용량 기록 + 응답 캐시.

- provider 'openai' : gpt-4o-mini / text-embedding-3-small (Streamlit Cloud 배포용)
- provider 'ollama' : qwen3.5:9b / bge-m3 (로컬 PC, 비용 0, 데이터가 PC 밖으로 나가지 않음)
OpenAI 호출이 실패하면(키 없음·장애) 로컬 Ollama 로 자동 전환(fallback)을 시도한다.
"""
from __future__ import annotations

import os
from functools import lru_cache

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.globals import set_llm_cache

from core import applog
from core.config import (APP_DB, LLM_MAX_RETRIES, LLM_TIMEOUT, OLLAMA_CHAT_MODEL,
                         OLLAMA_EMBED_MODEL, OPENAI_CHAT_MODEL, OPENAI_EMBED_MODEL, PROVIDER, secret)

_cache_on = False


def enable_cache() -> None:
    """같은 프롬프트는 다시 과금하지 않도록 SQLite 캐시를 켠다."""
    global _cache_on
    if not _cache_on:
        from langchain_community.cache import SQLiteCache
        set_llm_cache(SQLiteCache(database_path=str(APP_DB.with_name("llm_cache.db"))))
        _cache_on = True


_openai_state = {"ok": None, "checked": 0.0, "reason": "확인 전"}


def openai_ok() -> bool:
    """키가 있고 실제로 호출 가능한지 확인한다.

    성공은 계속 기억하고, 실패는 60초 뒤 다시 확인한다
    (배포 뒤 Secrets 를 넣거나 크레딧을 충전해도 재시작 없이 반영되도록).
    """
    import time
    st_ = _openai_state
    if st_["ok"] or (st_["ok"] is False and time.time() - st_["checked"] < 60):
        return bool(st_["ok"])
    key = secret("OPENAI_API_KEY")
    st_["checked"] = time.time()
    if not key:
        st_.update(ok=False, reason="OPENAI_API_KEY 가 없습니다 (Secrets 확인)")
        return False
    if not str(key).startswith("sk-"):
        st_.update(ok=False, reason="키 형식이 sk- 로 시작하지 않습니다")
        return False
    try:
        from openai import OpenAI
        # 인증만이 아니라 '실제 호출 가능(크레딧 잔액)'까지 확인: 1토큰 임베딩, 비용 사실상 0
        OpenAI(api_key=key, timeout=8, max_retries=0).embeddings.create(
            model=OPENAI_EMBED_MODEL, input="ok")
        st_.update(ok=True, reason="정상")
        return True
    except Exception as e:
        code = getattr(e, "status_code", "")
        reason = {401: "인증 실패(키 확인)", 429: "크레딧 부족 또는 호출 한도"}.get(code, type(e).__name__)
        st_.update(ok=False, reason=f"{reason} {code}".strip())
        applog.log.warning("OpenAI 사용 불가 → 로컬 모델 사용: %s", st_["reason"])
        return False


def openai_reason() -> str:
    return _openai_state["reason"]


def current_provider() -> str:
    p = os.getenv("NAMDO_PROVIDER", PROVIDER)
    if p == "openai" and not openai_ok():
        return "ollama"
    return p


class UsageLogger(BaseCallbackHandler):
    """LLM 호출마다 토큰·지연시간을 app.db에 남긴다 (관리자 화면에서 집계)."""

    def __init__(self, feature: str, question: str = ""):
        self.feature, self.question = feature, question
        self._t: dict = {}

    def on_chat_model_start(self, serialized, messages, *, run_id, **kw):
        import time
        self._t[run_id] = time.perf_counter()

    def on_llm_start(self, serialized, prompts, *, run_id, **kw):
        import time
        self._t[run_id] = time.perf_counter()

    def on_llm_end(self, response, *, run_id, **kw):
        import time
        ms = int((time.perf_counter() - self._t.pop(run_id, time.perf_counter())) * 1000)
        pt = ct = 0
        model = ""
        try:
            gen = response.generations[0][0]
            meta = getattr(gen.message, "usage_metadata", None) or {}
            pt, ct = meta.get("input_tokens", 0), meta.get("output_tokens", 0)
            model = (gen.message.response_metadata or {}).get("model_name", "") or \
                    (gen.message.response_metadata or {}).get("model", "")
        except Exception:
            pass
        applog.record_llm(self.feature, current_provider(), model.split("-2024")[0] or "?",
                          pt, ct, ms, True, "", self.question)

    def on_llm_error(self, error, *, run_id, **kw):
        applog.record_llm(self.feature, current_provider(), "?", 0, 0, 0, False, str(error), self.question)


def chat(temperature: float = 0.3, provider: str | None = None, json_mode: bool = False):
    provider = provider or current_provider()
    enable_cache()
    if provider == "ollama":
        from langchain_ollama import ChatOllama
        kw = {"format": "json"} if json_mode else {}
        # qwen3.5 의 '생각(thinking)' 출력은 끈다: 응답이 빠르고 JSON 파싱이 안정적
        return ChatOllama(model=OLLAMA_CHAT_MODEL, temperature=temperature, reasoning=False, **kw)
    from langchain_openai import ChatOpenAI
    kw = {"model_kwargs": {"response_format": {"type": "json_object"}}} if json_mode else {}
    return ChatOpenAI(model=OPENAI_CHAT_MODEL, temperature=temperature, timeout=LLM_TIMEOUT,
                      max_retries=LLM_MAX_RETRIES, api_key=secret("OPENAI_API_KEY"), **kw)


@lru_cache(maxsize=2)
def embeddings(provider: str | None = None):
    provider = provider or current_provider()
    if provider == "ollama":
        from langchain_ollama import OllamaEmbeddings
        return OllamaEmbeddings(model=OLLAMA_EMBED_MODEL)
    from langchain_openai import OpenAIEmbeddings
    return OpenAIEmbeddings(model=OPENAI_EMBED_MODEL, api_key=secret("OPENAI_API_KEY"))


def openai_client():
    from openai import OpenAI
    return OpenAI(api_key=secret("OPENAI_API_KEY"), timeout=LLM_TIMEOUT, max_retries=LLM_MAX_RETRIES)


def ollama_ok() -> bool:
    import requests
    try:
        return requests.get("http://localhost:11434/api/tags", timeout=0.5).ok
    except Exception:
        return False
