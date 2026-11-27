# 배포 절차 (Streamlit Community Cloud)

> 비밀값(키·비밀번호)은 이 문서·코드·커밋 어디에도 적지 않습니다. 로컬은 `.streamlit/secrets.toml`, 클라우드는 앱 Secrets 화면에만 넣습니다.

## 1단계 · 로컬에서 키 넣고 점검 (5분)

1. `.streamlit/secrets.toml` 을 메모장으로 열고 `OPENAI_API_KEY = "..."` 의 따옴표 안에 **sk-로 시작하는 키**를 붙여 넣습니다.
   - 이 파일은 `.gitignore`로 GitHub에 올라가지 않습니다.
   - PC 환경변수에 다른 `OPENAI_API_KEY` 값이 있어도 이 파일의 값이 우선합니다.
2. 점검과 OpenAI 벡터 인덱스 빌드를 한 번에 실행합니다. 1~2분 걸리고, 임베딩 비용은 약 $0.02입니다.
   ```
   python -m scripts.prepare_deploy --build
   ```
   모든 줄이 ✅이고 마지막에 `배포 준비 완료`가 나오면 다음 단계로 넘어갑니다.
3. (선택) `streamlit run app.py` 로 사이드바에서 **☁️ OpenAI** 를 고르고 여행 추천·챗봇·음성 안내를 확인합니다.

## 2단계 · GitHub 저장소 (사용자 확인 후 진행)

1. github.com 에서 새 저장소를 만듭니다. 예: `namdo-ai-planner`. README는 만들지 않습니다.
   - Public이면 코드가 공개됩니다. 데이터는 공공데이터뿐이고 비밀값은 커밋하지 않습니다.
   - Private도 Streamlit Cloud에 연결할 수 있습니다.
2. 커밋하고 푸시합니다.
   ```
   git add -A
   git commit -m "남도ON AI 여행 플래너 최종 결과물"
   git remote add origin https://github.com/<계정>/namdo-ai-planner.git
   git push -u origin main
   ```
   커밋 대상은 약 30MB입니다(코드, `tour.db`, OpenAI 벡터 인덱스, PDF 2종).

## 3단계 · Streamlit Cloud 배포

1. https://share.streamlit.io 접속 → **Create app** → **Deploy a public app from GitHub**
2. Repository `<계정>/namdo-ai-planner`, Branch `main`, Main file `app.py`
3. **Advanced settings**
   - Python version: **3.12**
   - Secrets 칸에 아래 형식으로 붙여 넣기 (값은 직접 입력)
     ```
     OPENAI_API_KEY = "sk-..."
     ADMIN_PASSWORD = "로컬과 다른 새 비밀번호"
     ```
     `DATA_GO_KR_KEY`는 클라우드에서 쓰지 않습니다. 데이터 수집은 로컬 스케줄러가 맡습니다.
4. **Deploy** → 첫 빌드는 3~5분 걸립니다. 첫 검색 때 리랭커 모델(약 100MB)을 내려받습니다.

## 4단계 · 배포 후 확인

- [ ] 홈 지표(3,712건 등)가 보인다
- [ ] 사이드바 AI 모델에 ☁️ OpenAI 만 보인다 (클라우드에는 Ollama 없음)
- [ ] AI 여행 추천 1건 생성 (약 20~40초)
- [ ] 챗봇 예시 질문 2개 (대화 기억)
- [ ] 사진으로 찾기: 'AI 비전' 방식만 보인다 (CLIP은 로컬 전용)
- [ ] 관리자 로그인 → 방금 호출이 기록됨

## 클라우드와 로컬의 차이

| 기능 | 로컬 PC | Streamlit Cloud |
|---|---|---|
| AI 모델 | OpenAI ↔ Ollama 전환 | OpenAI |
| 사진 검색 | AI 비전 + CLIP | AI 비전 |
| 데이터 자동 갱신 | `python -m scripts.scheduler` | 없음 → 로컬에서 갱신 후 다시 푸시 |
| 운영 로그(app.db) | 계속 유지 | 앱 재시작 시 초기화 |

## 데이터 갱신 후 다시 배포
```
python -m scripts.scheduler --once     # 수집 → DB → 인덱스
git add data/tour.db data/index/faiss_openai.bin
git commit -m "관광 데이터 갱신"
git push
```
Streamlit Cloud는 푸시를 감지해 자동으로 다시 배포합니다.
