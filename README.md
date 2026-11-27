# 🌿 남도ON AI 여행 플래너

**데이터로 근거를 대고, AI로 계획하는 남도 여행** — 전남광주통합특별시 공공 관광데이터 위에
LangGraph 멀티에이전트, 하이브리드 RAG, 멀티모달 검색을 얹은 스마트 관광 AI 통합 서비스입니다.
(2026 전남ICT이노베이션스퀘어 「스마트 관광 AI 서비스 개발」 최종 프로젝트 · C안 풀스택 심화형)

## 1. 핵심 기능

| 화면 | 기능 | 사용 기술 |
|---|---|---|
| 🧭 AI 여행 추천 | 지역·기간·동행·테마 → 근거 있는 일정, 지도 동선, 근처 음식점·숙박, 음성·다국어 | LangGraph 멀티에이전트(9노드, 병렬·조건 분기·재시도 루프), Haversine |
| 💬 관광 안내 챗봇 | 질문에 맞는 도구를 골라 답하고 출처 표시, 대화 기억 | `create_agent` + 도구 6종, InMemorySaver, 하이브리드 RAG |
| 📷 사진으로 찾기 | 풍경 사진 → 비슷한 관광지 | AI 비전(GPT-4o-mini / 로컬 qwen3.5) + CLIP(ViT-B-32) 코사인 유사도 |
| 🗺️ 관광지 탐색 | 3,712곳 지도·필터·즐겨찾기, 지역별 방문 추이 | Folium MarkerCluster, Plotly |
| 🛠️ 관리자 | AI 호출·토큰·비용·응답시간·오류율, 데이터 갱신 작업, 의견 | SQLite 로그, 콜백, hmac 로그인 |
| 📚 데이터·AI 윤리 | 출처, 신뢰성·편향성·가용성·책임성 원칙, 한계 | — |

## 2. 멀티에이전트 플래너 구조

```
intake(조건 해석) → scout(후보 탐색: DB + 하이브리드 검색)
                       ├→ analyst(방문자·체류·소비 근거 + 축제)  ┐  병렬 실행 후 합류
                       └→ weather(Open-Meteo 16일 예보)         ┘
                 → planner(후보 번호만 골라 일정 작성, 구조화 출력)
                 → route(최근접 동선 정렬) → validator(DB 대조 검증)
                       ├─ 문제 있음 & 2회 미만 → planner 로 되돌림(피드백 포함)
                       ├─ 2회 초과 → repair(규칙 보정: 중복 제거·근처 후보 보충)
                       └─ 통과 → finalize(근처 음식점·숙박 DB 연결)
```

**환각 방지 3중 장치**
1. 플래너는 후보 목록의 번호(P01…)만 고를 수 있고, 이름·좌표·사진은 DB에서 다시 붙입니다.
2. 검증 에이전트가 목록 밖 장소·중복·하루 80km 초과를 찾아 재작성시킵니다.
3. 근거 수치 문장은 **코드가 DB 값으로 직접** 쓰고, LLM은 숫자 없는 해석 한 문장만 씁니다.
   (개발 중 LLM이 방문자 수를 바꿔 쓰는 문제를 발견해 이렇게 바꿨고, 회귀 테스트로 지킵니다.)

## 3. 데이터

| 데이터 | 출처 | 규모 |
|---|---|---|
| 관광 콘텐츠·소개글·축제 | 한국관광공사 TourAPI KorService2 | 3,712건 (관광지 1,513 · 음식점 1,016 · 쇼핑 359 · 숙박 289 · 문화시설 270 · 레포츠 194), 축제 65 |
| 추정 방문자 | 한국관광공사 관광빅데이터 | 27개 시군구 × 2025.09~2026.06 일별 → 월 집계 |
| 관광 수요 강도 | 한국관광공사 | 체류 5종·소비 3종 지표 |
| RAG 문서 | 과정 제공 관광 홍보물 PDF 2종 | 15쪽 |

> **발견:** 2026년 행정구역 개편으로 전남·광주는 법정동 코드 `12`(전남광주통합특별시)로 조회해야 합니다.
> 옛 `areaCode`(38/5)로는 1,223건만 나와서, 미니 프로젝트(남도ON) 대비 데이터가 3배로 늘었습니다.
> 소개글(detailCommon2)은 일일 호출 한도 1,000건이라 스케줄러가 매일 이어받습니다.

`data/tour.db` 표: `places`, `festivals`, `sigungu`, `visitors_monthly`, `demand`, `meta`
`data/app.db` 표: `llm_calls`, `jobs`, `feedback`, `favorites` (운영 기록, 커밋 제외)

## 4. 실행 방법

```bash
pip install -r requirements-local.txt          # 로컬 전체 기능 (클라우드는 requirements.txt)
copy .streamlit\secrets.toml.example .streamlit\secrets.toml   # 키 입력

# 데이터 → DB → 인덱스 (처음 한 번)
python -m scripts.collect_tourapi list
python -m scripts.collect_tourapi detail 990
python -m scripts.build_db
python -m scripts.build_index text openai      # 또는 text ollama (로컬 bge-m3)
python -m scripts.build_index clip             # 로컬 GPU 이미지 인덱스

streamlit run app.py
python -m scripts.scheduler                    # 매일 06:00 자동 갱신 (상시 실행)
python -m pytest -q                            # 테스트 17개
```

**배포:** Streamlit Cloud 배포 절차는 [DEPLOY.md](DEPLOY.md) 참고 (`python -m scripts.prepare_deploy --build` 로 점검).

**AI 모델 전환:** 사이드바에서 ☁️ OpenAI(gpt-4o-mini) ↔ 🖥️ 로컬 Ollama(qwen3.5:9b + bge-m3).
OpenAI 키가 없거나 인증에 실패하면 자동으로 로컬 모델을 씁니다. 음성 안내(TTS)는 OpenAI 전용입니다.

## 5. 시연 시나리오 (5분)

1. **홈** — 3,712건·소개글·축제·시군구 지표, "옛 지역코드 → 통합특별시 코드" 발견 이야기
2. **AI 여행 추천** — 목포 · 1박 2일 · 부모님 · 역사·문화+바다 · 여유 · 혼잡 회피
   → 진행 상태에서 에이전트 활동이 실시간으로 표시됨 → 비 예보 시 실내 우선, 데이터 근거 패널, 지도 동선
3. **관광 안내 챗봇** — "여수는 몇 월이 제일 한산해?" → "그럼 그 달에 갈 만한 바다 명소 3곳" (대화 기억)
   → "오늘 서울 맛집" (범위 밖 거절)
4. **사진으로 찾기** — 순천만 갈대 데크길 사진: CLIP은 습지·갈대 명소를 찾고, 비전 모델 설명과 비교
5. **관리자** — 방금 호출들의 토큰·응답시간·오류율, 자동 갱신 작업 기록, LangGraph 구조

## 6. 폴더 구조

```
app.py                 Streamlit 진입점 (st.navigation)
core/  config · db · llm · retriever · planner · chat_agent · vision · media · weather · geo · applog · ui
views/ home · explore · planner · chatbot · photo · admin · about
scripts/ collect_tourapi · build_db · build_index · scheduler
data/  tour.db · docs/*.pdf · index/faiss_*.bin · clip/
tests/ test_core.py
```

## 7. 보안·운영
- 키는 `secrets.toml`/환경변수/`st.secrets`에만 저장합니다. `.gitignore`로 커밋을 막습니다.
- `tour.db`는 읽기 전용으로 열고 모든 SQL은 `?` 바인딩을 씁니다. 에이전트 도구는 허용된 읽기 함수만 호출합니다.
- 입력은 500자로 제한하고, LLM 호출에는 60초 timeout과 2회 retry를 둡니다. SQLite LLM 캐시와 실패 시 로컬 모델 fallback도 갖췄습니다.
- 업로드 사진은 저장하지 않습니다. 질문은 200자까지만 로그에 남깁니다.
