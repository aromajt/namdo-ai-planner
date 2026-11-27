"""사진으로 여행지 찾기.

방법 1 (클라우드·기본) GPT 비전: 사진 → 풍경 태그·설명(JSON) → 하이브리드 텍스트 검색
방법 2 (로컬 GPU)     CLIP:     사진 임베딩 ↔ 관광지 대표사진 임베딩 코사인 유사도

업로드 사진은 메모리에서만 처리하고 저장하지 않는다(개인정보 보호).
"""
from __future__ import annotations

import base64
import io
import json
import time
from functools import lru_cache

import numpy as np
from PIL import Image

from core import applog, db, retriever
from core.config import CLIP_DIR, OPENAI_CHAT_MODEL
from core.llm import openai_client

VISION_PROMPT = """이 사진의 여행 풍경을 분석해 JSON으로만 답해라.
{"scene": "한 문장 장면 설명", "tags": ["풍경 키워드 3~6개 (예: 바다, 대나무숲, 사찰, 야경, 갯벌, 정원)"],
 "type": "자연/문화역사/체험/도시/음식 중 하나", "mood": "분위기 2~3단어",
 "people_count_estimate": "사람 수 대략(0, 1~5, 6~20, 20 이상)"}
사람 얼굴·신원은 묘사하지 마라."""


def _to_jpeg_b64(img: Image.Image, max_side: int = 768) -> str:
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def describe(img: Image.Image) -> dict:
    from core.llm import current_provider
    if current_provider() == "ollama":
        return describe_local(img)
    t0 = time.perf_counter()
    resp = openai_client().chat.completions.create(
        model=OPENAI_CHAT_MODEL, response_format={"type": "json_object"}, temperature=0.2,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": VISION_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_to_jpeg_b64(img)}",
                                                "detail": "low"}}]}])
    u = resp.usage
    applog.record_llm("photo.vision", "openai", OPENAI_CHAT_MODEL, u.prompt_tokens, u.completion_tokens,
                      int((time.perf_counter() - t0) * 1000), True, "", "[이미지]")
    return json.loads(resp.choices[0].message.content)


def describe_local(img: Image.Image) -> dict:
    """로컬 qwen3.5(이미지 입력 지원)로 같은 분석. 사진이 PC 밖으로 나가지 않는다."""
    import requests
    from core.config import OLLAMA_CHAT_MODEL
    t0 = time.perf_counter()
    r = requests.post("http://localhost:11434/api/chat", timeout=180, json={
        "model": OLLAMA_CHAT_MODEL, "stream": False, "format": "json", "think": False,
        "options": {"temperature": 0.2},
        "messages": [{"role": "user", "content": VISION_PROMPT, "images": [_to_jpeg_b64(img, 640)]}]})
    r.raise_for_status()
    j = r.json()
    applog.record_llm("photo.vision", "ollama", OLLAMA_CHAT_MODEL, j.get("prompt_eval_count", 0),
                      j.get("eval_count", 0), int((time.perf_counter() - t0) * 1000), True, "", "[이미지]")
    return json.loads(j["message"]["content"])


def search_by_description(info: dict, sigungu: str | None = None, k: int = 6) -> list[dict]:
    query = f"{info.get('scene', '')} {' '.join(info.get('tags', []))} {info.get('type', '')}"
    docs = retriever.search(query, k=k, sigungu=sigungu, kinds=("place",))
    ids = [d.metadata["contentid"] for d in docs]
    df = db.place_by_ids(ids).set_index("contentid")
    return [df.loc[i].to_dict() | {"contentid": i} for i in ids if i in df.index]


# ---------------------------------------------------------------- CLIP (로컬)
def clip_available() -> bool:
    try:
        import open_clip  # noqa: F401
        import torch  # noqa: F401
        return (CLIP_DIR / "image_emb.npy").exists()
    except ImportError:
        return False


@lru_cache(maxsize=1)
def _clip():
    import open_clip
    import torch
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
    model.eval().to(dev)
    tok = open_clip.get_tokenizer("ViT-B-32")
    return model, preprocess, tok, dev


def clip_image_embedding(imgs: list[Image.Image]) -> np.ndarray:
    import torch
    model, preprocess, _, dev = _clip()
    with torch.no_grad():
        x = torch.stack([preprocess(i.convert("RGB")) for i in imgs]).to(dev)
        e = model.encode_image(x).float()
        e = e / e.norm(dim=-1, keepdim=True)
    return e.cpu().numpy()


def clip_text_embedding(texts: list[str]) -> np.ndarray:
    import torch
    model, _, tok, dev = _clip()
    with torch.no_grad():
        e = model.encode_text(tok(texts).to(dev)).float()
        e = e / e.norm(dim=-1, keepdim=True)
    return e.cpu().numpy()


@lru_cache(maxsize=1)
def _clip_index():
    emb = np.load(CLIP_DIR / "image_emb.npy")
    ids = json.loads((CLIP_DIR / "image_ids.json").read_text(encoding="utf-8"))
    return emb, ids


def clip_search(img: Image.Image | None = None, text: str | None = None, k: int = 6,
                sigungu: str | None = None) -> list[dict]:
    """이미지 또는 영어 문장으로 비슷한 관광지 사진을 찾는다(코사인 유사도)."""
    emb, ids = _clip_index()
    q = clip_image_embedding([img])[0] if img is not None else clip_text_embedding([text])[0]
    sims = emb @ q
    order = np.argsort(-sims)
    df = db.place_by_ids([ids[i] for i in order[:200]]).set_index("contentid")
    out = []
    for i in order[:200]:
        cid = ids[i]
        if cid not in df.index:
            continue
        row = df.loc[cid].to_dict()
        if sigungu and row["sigungu_name"] != sigungu:
            continue
        out.append(row | {"contentid": cid, "similarity": float(sims[i])})
        if len(out) >= k:
            break
    return out
