"""배포 직전 점검 + OpenAI 인덱스 빌드를 한 번에.

  python -m scripts.prepare_deploy          # 점검만
  python -m scripts.prepare_deploy --build  # OpenAI 키 확인 후 벡터 인덱스 빌드까지

비밀값은 출력하지 않는다(키 앞 3글자·길이·인증 결과만).
"""
from __future__ import annotations

import subprocess
import sys

from core.config import DOCS_DIR, INDEX_DIR, ROOT, TOUR_DB, secret

OK, NG = "✅", "❌"
problems: list[str] = []


def check(cond: bool, msg: str, fix: str = "") -> None:
    print(f"{OK if cond else NG} {msg}")
    if not cond:
        problems.append(f"{msg} → {fix}" if fix else msg)


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    return r.stdout.strip()


def main(build: bool) -> None:
    print("== 1. 키 ==")
    key = secret("OPENAI_API_KEY") or ""
    auth = usable = False
    if key:
        from openai import OpenAI
        client = OpenAI(api_key=key, timeout=10, max_retries=0)
        try:
            client.models.list()
            auth = True
            client.embeddings.create(model="text-embedding-3-small", input="ok")
            usable = True
        except Exception as e:
            print(f"   OpenAI 오류: {type(e).__name__} {getattr(e, 'status_code', '')}")
    check(key.startswith("sk-"), f"OpenAI 키 형식 (앞 3글자 '{key[:3]}', 길이 {len(key)})",
          ".streamlit/secrets.toml 의 OPENAI_API_KEY 에 sk-로 시작하는 키를 넣으세요")
    check(auth, "OpenAI 인증", "키가 맞는지 확인")
    check(usable, "OpenAI 실제 호출(크레딧 잔액)",
          "platform.openai.com → Settings → Billing 에서 크레딧 충전 또는 과정 지원 키 사용")
    auth = usable
    check(bool(secret("DATA_GO_KR_KEY")), "공공데이터포털 키")
    check(bool(secret("ADMIN_PASSWORD")), "관리자 비밀번호")

    print("== 2. 데이터·인덱스 ==")
    if build and auth:
        from scripts.build_index import build_text
        build_text("openai")
    check(TOUR_DB.exists(), f"tour.db ({TOUR_DB.stat().st_size // 1024}KB)" if TOUR_DB.exists() else "tour.db")
    check(any(DOCS_DIR.glob("*.pdf")), "RAG 문서 PDF")
    idx = INDEX_DIR / "faiss_openai.bin"
    check(idx.exists(), "OpenAI 벡터 인덱스 (data/index/faiss_openai.bin)",
          "키를 넣은 뒤 python -m scripts.prepare_deploy --build")

    print("== 3. Git 안전 ==")
    if (ROOT / ".git").exists():
        tracked = git("ls-files").splitlines()
        check(".streamlit/secrets.toml" not in tracked, "secrets.toml 이 커밋 대상이 아님")
        check(not any(t.startswith("data/raw/") for t in tracked), "원천 응답(data/raw) 제외")
        leak = git("grep", "-nIE", r"sk-[A-Za-z0-9_-]{20,}|serviceKey=[A-Za-z0-9%+/=]{40,}", "--", ".")
        check(not leak, "커밋된 파일에 키 문자열 없음", leak[:200])
    else:
        print("   (아직 git 저장소 아님)")

    print("== 4. 테스트 ==")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8")
    last = (r.stdout.strip().splitlines() or ["?"])[-1]
    check(r.returncode == 0, f"pytest: {last}")

    print("\n결과:", "배포 준비 완료" if not problems else f"남은 문제 {len(problems)}건")
    for p in problems:
        print("  -", p)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main("--build" in sys.argv)
