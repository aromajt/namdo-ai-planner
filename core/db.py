"""tour.db 조회 함수 모음.

보안 원칙: SQL 문자열에 사용자 입력을 직접 붙이지 않는다(항상 ? 바인딩).
에이전트 도구도 이 함수만 호출하게 해서 임의 SQL 실행을 막는다.
"""
from __future__ import annotations

import sqlite3
from functools import lru_cache

import pandas as pd

from core.config import TOUR_DB, VISIT_TYPES


def _con() -> sqlite3.Connection:
    # 읽기 전용으로 연다 (서비스 중 원천 데이터가 바뀌지 않도록)
    return sqlite3.connect(f"file:{TOUR_DB.as_posix()}?mode=ro", uri=True, check_same_thread=False)


def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    with _con() as con:
        return pd.read_sql(sql, con, params=params)


@lru_cache(maxsize=1)
def sigungu_df() -> pd.DataFrame:
    return query("SELECT * FROM sigungu ORDER BY region DESC, code")


def sigungu_names() -> list[str]:
    return sigungu_df()["name"].tolist()


def normalize_sigungu(text: str) -> str | None:
    """'여수', '여수시', '광주 동구' 같은 표현을 DB의 시군구 이름으로 맞춘다."""
    if not text:
        return None
    t = text.replace(" ", "")
    names = sigungu_names()
    for n in names:
        if n in t or n.rstrip("시군구") == t or (len(n) > 2 and n[:-1] in t):
            return n
    return None


def meta() -> dict:
    return dict(query("SELECT key, value FROM meta").values.tolist())


def places(sigungu: str | None = None, types: tuple[str, ...] | None = None,
           keyword: str | None = None, with_coords: bool = True, limit: int = 3000) -> pd.DataFrame:
    sql = "SELECT * FROM places WHERE 1=1"
    params: list = []
    if sigungu:
        sql += " AND sigungu_name = ?"
        params.append(sigungu)
    if types:
        sql += f" AND type_id IN ({','.join('?' * len(types))})"
        params += list(types)
    if keyword:
        sql += " AND (title LIKE ? OR overview LIKE ? OR cat3 LIKE ? OR cat2 LIKE ?)"
        params += [f"%{keyword}%"] * 4
    if with_coords:
        sql += " AND lat IS NOT NULL"
    sql += " LIMIT ?"
    params.append(int(limit))
    return query(sql, tuple(params))


def visit_candidates(sigungu: str) -> pd.DataFrame:
    return places(sigungu, VISIT_TYPES)


def place_by_ids(ids: list[str]) -> pd.DataFrame:
    if not ids:
        return pd.DataFrame()
    return query(f"SELECT * FROM places WHERE contentid IN ({','.join('?' * len(ids))})", tuple(ids))


def festivals(sigungu: str | None = None, month: str | None = None) -> pd.DataFrame:
    """month='YYYYMM' 이면 그 달에 진행 중인 행사만."""
    sql, params = "SELECT * FROM festivals WHERE 1=1", []
    if sigungu:
        sql += " AND sigungu_name = ?"
        params.append(sigungu)
    if month:
        sql += " AND substr(start_date,1,6) <= ? AND substr(end_date,1,6) >= ?"
        params += [month, month]
    return query(sql + " ORDER BY start_date", tuple(params))


def visitor_profile(sigungu: str) -> pd.DataFrame:
    """월별 일평균 추정 방문자 (현지인·외지인·외국인)."""
    df = query("SELECT * FROM visitors_monthly WHERE sigungu_name = ? ORDER BY ym", (sigungu,))
    for c in ("local", "outsider", "foreigner"):
        df[c + "_daily"] = df[c] / df["days"]
    return df


def demand_latest(sigungu: str) -> pd.DataFrame:
    return query("""SELECT d.* FROM demand d
                    WHERE sigungu_name = ? AND ym = (SELECT max(ym) FROM demand WHERE sigungu_name = ?)""",
                 (sigungu, sigungu))


def evidence_numbers(sigungu: str, month: int | None = None) -> dict:
    """추천 근거로 쓸 '실제 수치'만 계산해서 돌려준다. LLM은 이 값만 인용한다."""
    out: dict = {"시군구": sigungu}
    vp = visitor_profile(sigungu)
    if not vp.empty:
        avg = vp["outsider_daily"].mean()
        out["외지인 일평균 추정 방문(전체 기간)"] = round(avg)
        out["자료 기간"] = f"{vp.ym.min()}~{vp.ym.max()}"
        if month:
            sel = vp[vp.ym.str[4:].astype(int) == month]
            if not sel.empty:
                v = sel["outsider_daily"].mean()
                out[f"{month}월 외지인 일평균 추정 방문"] = round(v)
                out[f"{month}월 혼잡 수준(평균 대비)"] = f"{v / avg * 100:.0f}%"
        busiest = vp.loc[vp["outsider_daily"].idxmax()]
        quiet = vp.loc[vp["outsider_daily"].idxmin()]
        out["가장 붐빈 달"] = f"{busiest.ym[:4]}.{busiest.ym[4:]}"
        out["가장 한산한 달"] = f"{quiet.ym[:4]}.{quiet.ym[4:]}"
    dm = demand_latest(sigungu)
    for _, r in dm.iterrows():
        out[f"[{r.kind}] {r.indicator} ({r.ym[:4]}.{r.ym[4:]})"] = r.value
    # 같은 지표의 전남·광주 시군구 평균과 비교
    if not dm.empty:
        allm = query("SELECT indicator, avg(value) v FROM demand WHERE ym = ? GROUP BY indicator",
                     (dm.ym.iloc[0],))
        for _, r in allm.iterrows():
            out[f"(비교) {r.indicator} 시군구 평균"] = round(r.v, 2)
    return out
