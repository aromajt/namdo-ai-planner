"""하이브리드 검색: BM25(키워드) + FAISS(의미) → FlashRank 리랭킹.

문서 출처
  1) tour.db 관광 콘텐츠·축제 (TourAPI 소개글)
  2) data/docs/*.pdf (전남·광주 관광 홍보물)
모든 검색 결과에는 출처(source)와 contentid가 붙어 있어 답변에 근거로 표시한다.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from langchain_core.documents import Document

from core import db
from core.config import DOCS_DIR, INDEX_DIR
from core.llm import current_provider, embeddings


def _tokens(text: str) -> list[str]:
    """한국어용 간단 토크나이저: 어절 + 글자 2-gram (조사가 붙어도 매칭되도록)."""
    words = re.findall(r"[가-힣A-Za-z0-9]+", text.lower())
    grams = [w[i:i + 2] for w in words if len(w) > 1 for i in range(len(w) - 1)]
    return words + grams


def place_documents() -> list[Document]:
    docs = []
    for r in db.query("SELECT * FROM places").itertuples():
        cats = "/".join(x for x in [r.type_name, r.cat2, r.cat3] if x)
        text = f"{r.title} ({cats}) - {r.region} {r.sigungu_name}\n주소: {r.addr}\n{r.overview or ''}"
        docs.append(Document(page_content=text.strip(), metadata={
            "source": "TourAPI 관광정보", "contentid": r.contentid, "title": r.title,
            "sigungu": r.sigungu_name, "type_id": r.type_id, "kind": "place"}))
    for r in db.query("SELECT * FROM festivals").itertuples():
        text = (f"{r.title} (축제·행사) - {r.region} {r.sigungu_name}\n기간: {r.start_date}~{r.end_date}\n"
                f"장소: {r.addr}\n{r.overview or ''}")
        docs.append(Document(page_content=text.strip(), metadata={
            "source": "TourAPI 축제정보", "contentid": r.contentid, "title": r.title,
            "sigungu": r.sigungu_name, "type_id": "15", "kind": "festival"}))
    return docs


def pdf_documents() -> list[Document]:
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=80)
    out = []
    for pdf in sorted(Path(DOCS_DIR).glob("*.pdf")):
        pages = PyPDFLoader(str(pdf)).load()
        for d in splitter.split_documents(pages):
            d.metadata = {"source": f"{pdf.stem} p.{d.metadata.get('page', 0) + 1}",
                          "title": pdf.stem, "kind": "pdf", "contentid": ""}
            out.append(d)
    return out


def all_documents() -> list[Document]:
    return place_documents() + pdf_documents()


def build_vector_index(provider: str) -> int:
    import time

    from langchain_community.vectorstores import FAISS
    docs = all_documents()
    emb = embeddings(provider)
    vs, step = None, 64          # 로컬 모델이 한 번에 받을 수 있게 64건씩 나눠 임베딩
    for i in range(0, len(docs), step):
        batch = docs[i:i + step]
        for attempt in range(3):
            try:
                if vs is None:
                    vs = FAISS.from_documents(batch, emb)
                else:
                    vs.add_documents(batch)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(5 * (attempt + 1))
        print(f"  임베딩 {min(i + step, len(docs))}/{len(docs)}", flush=True)
    # FAISS C++ 저장 함수는 한글 경로를 못 열어서, 바이트로 직렬화해 파이썬으로 저장한다
    index_path(provider).write_bytes(vs.serialize_to_bytes())
    return len(docs)


def index_path(provider: str) -> Path:
    return INDEX_DIR / f"faiss_{provider}.bin"


@lru_cache(maxsize=2)
def _vector_store(provider: str):
    from langchain_community.vectorstores import FAISS
    return FAISS.deserialize_from_bytes(index_path(provider).read_bytes(), embeddings(provider),
                                        allow_dangerous_deserialization=True)  # 직접 만든 인덱스만 로드


@lru_cache(maxsize=1)
def _bm25():
    from langchain_community.retrievers import BM25Retriever
    r = BM25Retriever.from_documents(all_documents(), preprocess_func=_tokens)
    r.k = 20
    return r


@lru_cache(maxsize=1)
def _ranker():
    from flashrank import Ranker
    # 다국어(한국어 포함) 교차 인코더. 처음 한 번 모델을 내려받는다.
    return Ranker(model_name="ms-marco-MultiBERT-L-12", cache_dir=str(INDEX_DIR / "flashrank"))


def _rrf(lists: list[list[Document]], k: int = 60) -> list[Document]:
    """Reciprocal Rank Fusion: 두 검색 결과의 순위를 합친다 (EnsembleRetriever와 같은 원리)."""
    score: dict[str, float] = {}
    keep: dict[str, Document] = {}
    for lst in lists:
        for rank, d in enumerate(lst):
            key = d.metadata.get("contentid") or d.page_content[:80]
            score[key] = score.get(key, 0) + 1 / (k + rank + 1)
            keep.setdefault(key, d)
    return [keep[k_] for k_ in sorted(score, key=score.get, reverse=True)]


def search(query: str, k: int = 6, sigungu: str | None = None, kinds: tuple[str, ...] | None = None,
           rerank: bool = True) -> list[Document]:
    provider = current_provider()
    try:
        vec = _vector_store(provider).similarity_search(query, k=30)
    except Exception:  # 인덱스 파일이 없거나 임베딩 API 장애 → 키워드 검색만으로 계속
        vec = []
    kw = _bm25().invoke(query)
    merged = _rrf([vec, kw])

    def ok(d: Document) -> bool:
        if sigungu and d.metadata.get("kind") != "pdf" and d.metadata.get("sigungu") != sigungu:
            return False
        return not kinds or d.metadata.get("kind") in kinds

    cands = [d for d in merged if ok(d)]
    # 음식·숙박을 묻지 않았으면 음식점(39)·숙박(32)은 뒤로 (관광지 질문에 식당이 섞이지 않게)
    if not re.search(r"맛집|음식|식당|먹|카페|숙소|숙박|호텔|펜션|잠", query):
        cands = [d for d in cands if d.metadata.get("type_id") not in ("39", "32")] + \
                [d for d in cands if d.metadata.get("type_id") in ("39", "32")]
    cands = cands[:25]
    if not rerank or len(cands) <= k:
        return cands[:k]
    try:
        from flashrank import RerankRequest
        passages = [{"id": i, "text": d.page_content[:700]} for i, d in enumerate(cands)]
        res = _ranker().rerank(RerankRequest(query=query, passages=passages))
        # 리랭커 점수 + 하이브리드 순위를 함께 반영 (한국어 리랭커 점수 차가 작아서)
        fused = {r["id"]: 0.5 / (1 + pos) for pos, r in enumerate(res)}
        for i in range(len(cands)):
            fused[i] = fused.get(i, 0) + 0.5 / (1 + i)
        return [cands[i] for i in sorted(fused, key=fused.get, reverse=True)[:k]]
    except Exception:
        return cands[:k]   # 리랭커 실패 시 하이브리드 순위 그대로


def format_docs(docs: list[Document]) -> str:
    return "\n\n".join(f"[{i + 1}] 출처: {d.metadata['source']}"
                       + (f" (contentid={d.metadata['contentid']})" if d.metadata.get("contentid") else "")
                       + f"\n{d.page_content[:600]}" for i, d in enumerate(docs))
