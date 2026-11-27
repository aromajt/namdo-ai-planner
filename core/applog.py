"""서비스 운영 기록(app.db): LLM 호출 로그, 사용자 피드백, 즐겨찾기.

개인정보 원칙: 이름·연락처·업로드 사진은 저장하지 않는다. 질문 원문은 200자까지만 남긴다.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime

from core.config import APP_DB, DATA

_lock = threading.Lock()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    handlers=[logging.FileHandler(DATA / "service.log", encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("namdo")

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, feature TEXT, provider TEXT, model TEXT,
  prompt_tokens INTEGER, completion_tokens INTEGER, cost_usd REAL, latency_ms INTEGER,
  ok INTEGER, error TEXT, question TEXT);
CREATE TABLE IF NOT EXISTS feedback(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, feature TEXT, rating INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS favorites(
  session TEXT, contentid TEXT, title TEXT, ts TEXT, PRIMARY KEY(session, contentid));
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, job TEXT, ok INTEGER, detail TEXT);
"""

# gpt-4o-mini / text-embedding-3-small 공개 단가(USD / 1M tokens) — 비용 '추정'용
PRICE = {"gpt-4o-mini": (0.15, 0.60), "text-embedding-3-small": (0.02, 0.0)}


def _con():
    con = sqlite3.connect(APP_DB, check_same_thread=False)
    con.executescript(SCHEMA)
    return con


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def record_llm(feature: str, provider: str, model: str, prompt_tokens: int, completion_tokens: int,
               latency_ms: int, ok: bool = True, error: str = "", question: str = "") -> None:
    pin, pout = PRICE.get(model, (0.0, 0.0))
    cost = (prompt_tokens * pin + completion_tokens * pout) / 1_000_000
    with _lock, _con() as con:
        con.execute("INSERT INTO llm_calls(ts,feature,provider,model,prompt_tokens,completion_tokens,"
                    "cost_usd,latency_ms,ok,error,question) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (now(), feature, provider, model, prompt_tokens, completion_tokens, cost,
                     latency_ms, int(ok), error[:300], question[:200]))
    log.info("LLM %s %s tokens=%s/%s %dms ok=%s", feature, model, prompt_tokens,
             completion_tokens, latency_ms, ok)


def record_job(job: str, ok: bool, detail: str = "") -> None:
    with _lock, _con() as con:
        con.execute("INSERT INTO jobs(ts,job,ok,detail) VALUES (?,?,?,?)", (now(), job, int(ok), detail[:500]))


def add_feedback(feature: str, rating: int, note: str = "") -> None:
    with _lock, _con() as con:
        con.execute("INSERT INTO feedback(ts,feature,rating,note) VALUES (?,?,?,?)",
                    (now(), feature, rating, note[:300]))


def toggle_favorite(session: str, contentid: str, title: str) -> bool:
    with _lock, _con() as con:
        cur = con.execute("SELECT 1 FROM favorites WHERE session=? AND contentid=?", (session, contentid))
        if cur.fetchone():
            con.execute("DELETE FROM favorites WHERE session=? AND contentid=?", (session, contentid))
            return False
        con.execute("INSERT INTO favorites VALUES (?,?,?,?)", (session, contentid, title, now()))
        return True


def favorites(session: str) -> list[tuple[str, str]]:
    with _con() as con:
        return con.execute("SELECT contentid, title FROM favorites WHERE session=? ORDER BY ts DESC",
                           (session,)).fetchall()


def read_table(name: str, limit: int = 2000):
    import pandas as pd
    assert name in {"llm_calls", "feedback", "jobs", "favorites"}  # 허용 목록만
    with _con() as con:
        return pd.read_sql(f"SELECT * FROM {name} ORDER BY rowid DESC LIMIT ?", con, params=(limit,))


@contextmanager
def timer():
    t = {"start": time.perf_counter()}
    yield t
    t["ms"] = int((time.perf_counter() - t["start"]) * 1000)
