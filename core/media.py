"""음성 안내(TTS)와 다국어 번역."""
from __future__ import annotations

import time

from core import applog
from core.config import OPENAI_TTS_MODEL
from core.llm import UsageLogger, chat, openai_client


def tts(text: str, voice: str = "nova") -> bytes:
    """일정 요약을 mp3 음성으로 만든다 (OpenAI tts-1)."""
    t0 = time.perf_counter()
    text = text[:1500]
    resp = openai_client().audio.speech.create(model=OPENAI_TTS_MODEL, voice=voice, input=text)
    applog.record_llm("tts", "openai", OPENAI_TTS_MODEL, len(text), 0,
                      int((time.perf_counter() - t0) * 1000), True, "", "[TTS]")
    return resp.content


def translate(text: str, lang: str) -> str:
    prompt = (f"다음 한국어 여행 일정을 {lang}로 자연스럽게 번역해라. 고유명사(관광지 이름)는 "
              f"원어 발음 표기 뒤 괄호에 한글을 남겨라.\n\n{text}")
    return chat(0.2).invoke(prompt, config={"callbacks": [UsageLogger("translate", lang)]}).content


def plan_to_text(state: dict) -> str:
    """플래너 결과를 읽기 좋은 문장으로 (음성·번역·다운로드 공용)."""
    plan, days = state.get("plan", {}), state.get("days", [])
    lines = [plan.get("title", "여행 일정"), plan.get("summary", "")]
    for d in days:
        lines.append(f"{d['day']}일차, {d['theme']}.")
        for i, s in enumerate(d["stops"], 1):
            lines.append(f"{i}. {s['title']} - {s['reason']}")
    return "\n".join(x for x in lines if x)
