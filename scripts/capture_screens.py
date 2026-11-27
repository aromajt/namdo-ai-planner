"""발표 자료용 화면 캡처 (Playwright + 설치된 Chrome). 앱이 localhost:8501 에서 실행 중이어야 한다.

  python -m scripts.capture_screens
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from core.config import ROOT, secret

OUT = ROOT / "presentation" / "screens"
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://localhost:8501"
PHOTO = ROOT.parent / "vision_lec" / "images" / "tour1.jpg"


def settle(page, ms=1500):
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(ms)


def shot(page, name, full=False):
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
    print("saved", name)


def main(only: set[str]):
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2, locale="ko-KR")
        page = ctx.new_page()

        def go(path):
            page.goto(URL + path)
            page.get_by_text("남도ON AI", exact=False).first.wait_for(timeout=60000)
            settle(page, 2500)

        if not only or "home" in only:
            go("/")
            shot(page, "home")

        if not only or "explore" in only:
            go("/explore")
            page.wait_for_timeout(4000)
            shot(page, "explore")

        if not only or "planner" in only:
            go("/planner")
            page.get_by_role("button", name="AI 여행 일정 추천 받기").click()
            page.get_by_text("일정 완성!").wait_for(timeout=300000)
            settle(page, 4000)
            page.get_by_role("heading", level=3).first.scroll_into_view_if_needed()
            page.evaluate("window.scrollTo(0,0)")
            # 결과 제목 위치로 스크롤
            page.locator("h3").filter(has_text="일차").first.scroll_into_view_if_needed()
            page.mouse.wheel(0, -560)
            page.wait_for_timeout(2500)
            shot(page, "planner_top")
            page.locator("h3").filter(has_text="1일차").first.scroll_into_view_if_needed()
            page.mouse.wheel(0, -40)
            page.wait_for_timeout(2500)
            shot(page, "planner_days")
            page.get_by_text("에이전트 활동 기록").click()
            page.wait_for_timeout(800)
            page.get_by_text("에이전트 활동 기록").scroll_into_view_if_needed()
            page.mouse.wheel(0, 200)
            page.wait_for_timeout(800)
            shot(page, "planner_trace")

        if not only or "chat" in only:
            go("/chatbot")
            box = page.get_by_placeholder("예: 목포에서 비 오는 날 갈 만한 실내 명소는?")
            for q in ["여수는 몇 월이 제일 한산해?", "그럼 그 달에 갈 만한 바다 명소 3곳 추천해줘"]:
                box.fill(q)
                box.press("Enter")
                page.wait_for_timeout(1500)
                page.get_by_text("자료를 찾는 중…").wait_for(state="detached", timeout=180000)
                settle(page, 1500)
            page.mouse.wheel(0, 2000)
            page.wait_for_timeout(1000)
            shot(page, "chatbot")

        if not only or "photo" in only:
            for mode, name in [("CLIP", "photo_clip"), ("AI 비전", "photo_vision")]:
                go("/photo")
                page.get_by_text(mode, exact=False).first.click()
                page.wait_for_timeout(1000)
                page.locator("input[type=file]").set_input_files(str(PHOTO))
                page.get_by_text("비슷한 관광지를 찾는 중…").wait_for(state="detached", timeout=180000)
                settle(page, 4000)
                page.mouse.wheel(0, 330)
                page.wait_for_timeout(1500)
                shot(page, name)

        if not only or "admin" in only:
            go("/admin")
            page.get_by_label("관리자 비밀번호").fill(secret("ADMIN_PASSWORD"))
            page.get_by_role("button", name="로그인").click()
            page.get_by_text("AI 호출").first.wait_for(timeout=30000)
            settle(page, 3000)
            shot(page, "admin")

        b.close()


if __name__ == "__main__":
    main(set(sys.argv[1:]))
