"""검색 인덱스 빌드.

  python -m scripts.build_index text openai   # OpenAI 임베딩 FAISS (배포용)
  python -m scripts.build_index text ollama   # bge-m3 로컬 임베딩 FAISS
  python -m scripts.build_index clip          # 관광지 대표사진 CLIP 임베딩 (로컬 GPU)
"""
from __future__ import annotations

import io
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
from PIL import Image

from core import applog, db
from core.config import CLIP_DIR


def build_text(provider: str) -> None:
    from core.retriever import build_vector_index
    t = time.time()
    n = build_vector_index(provider)
    msg = f"{provider} 텍스트 인덱스 {n}개 문서, {time.time() - t:.0f}초"
    applog.record_job(f"index_{provider}", True, msg)
    print(msg)


def _fetch(url: str) -> Image.Image | None:
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception:
        return None


def build_clip() -> None:
    from core.vision import clip_image_embedding
    df = db.query("SELECT contentid, thumb, image FROM places "
                  "WHERE type_id IN ('12','14','28','38','15') AND (thumb <> '' OR image <> '')")
    print(f"대표사진 {len(df)}장 내려받아 임베딩")
    ids, embs = [], []
    rows = list(df.itertuples())
    for i in range(0, len(rows), 64):
        batch = rows[i:i + 64]
        with ThreadPoolExecutor(8) as ex:
            imgs = list(ex.map(lambda r: _fetch(r.thumb or r.image), batch))
        ok = [(r.contentid, im) for r, im in zip(batch, imgs) if im is not None]
        if ok:
            embs.append(clip_image_embedding([im for _, im in ok]))
            ids += [c for c, _ in ok]
        print(f"  {min(i + 64, len(rows))}/{len(rows)}")
    np.save(CLIP_DIR / "image_emb.npy", np.vstack(embs).astype(np.float32))
    (CLIP_DIR / "image_ids.json").write_text(json.dumps(ids), encoding="utf-8")
    applog.record_job("index_clip", True, f"{len(ids)}장")
    print(f"CLIP 인덱스 {len(ids)}장 저장")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "text"
    if what == "text":
        build_text(sys.argv[2] if len(sys.argv) > 2 else "openai")
    elif what == "clip":
        build_clip()
