"""관광 데이터 자동 갱신 스케줄러 (로컬 PC에서 상시 실행).

매일 06:00  목록·축제 재수집 → 소개글 미수집분 이어받기(일일 한도 내) → DB 재빌드 → 인덱스 재빌드
결과는 app.db 의 jobs 표에 남고, 관리자 화면에서 확인한다.

  python -m scripts.scheduler          # 상시 실행
  python -m scripts.scheduler --once   # 지금 한 번만 실행
"""
from __future__ import annotations

import sys
import time
import traceback

import schedule

from core import applog


def refresh() -> None:
    from core.llm import ollama_ok, openai_ok
    from scripts import build_db, collect_tourapi
    from scripts.build_index import build_text
    steps = [("collect_list", collect_tourapi.collect_list),
             ("collect_detail", lambda: collect_tourapi.collect_details(990)),
             ("build_db", build_db.build)]
    if openai_ok():
        steps.append(("index_openai", lambda: build_text("openai")))
    if ollama_ok():
        steps.append(("index_ollama", lambda: build_text("ollama")))
    for name, fn in steps:
        try:
            fn()
            applog.record_job(name, True, "ok")
        except Exception as e:  # 한 단계가 실패해도 기록하고 중단
            applog.record_job(name, False, f"{e}\n{traceback.format_exc()[-300:]}")
            applog.log.error("자동 갱신 실패 %s: %s", name, e)
            return
    applog.log.info("자동 갱신 완료")


if __name__ == "__main__":
    if "--once" in sys.argv:
        refresh()
        sys.exit(0)
    schedule.every().day.at("06:00").do(refresh)
    applog.log.info("스케줄러 시작: 매일 06:00 자동 갱신")
    while True:
        schedule.run_pending()
        time.sleep(30)
