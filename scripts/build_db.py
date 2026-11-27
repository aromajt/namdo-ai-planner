"""수집 원천(JSON/CSV) → data/tour.db (SQLite) 통합.

- places      : 관광 콘텐츠 (TourAPI 목록 + 상세 소개글)
- festivals   : 축제·공연·행사
- sigungu     : 시군구 코드표 (신 법정동 코드 ↔ 이름 ↔ 수요통계 코드)
- visitors_monthly : 이동통신 기반 추정 방문자(월 합계, 현지인/외지인/외국인)
- demand      : 관광 수요 강도 지표(체류·소비), 월별
- meta        : 수집·빌드 시각

실행: python -m scripts.build_db
"""
from __future__ import annotations

import html
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from core.config import CONTENT_TYPES, RAW, ROOT, TOUR_DB

# 미니 프로젝트(남도ON)에서 수집한 수요·방문자 CSV
LEGACY = ROOT.parent / "mystreamlit_git" / "data"
GWANGJU_GU = {"동구", "서구", "남구", "북구", "광산구"}

SCHEMA = """
DROP TABLE IF EXISTS places; DROP TABLE IF EXISTS festivals; DROP TABLE IF EXISTS sigungu;
DROP TABLE IF EXISTS visitors_monthly; DROP TABLE IF EXISTS demand; DROP TABLE IF EXISTS meta;
CREATE TABLE sigungu(
  code TEXT PRIMARY KEY, name TEXT NOT NULL, region TEXT NOT NULL,
  lat REAL, lon REAL, place_count INTEGER DEFAULT 0);
CREATE TABLE places(
  contentid TEXT PRIMARY KEY, title TEXT NOT NULL, type_id TEXT, type_name TEXT,
  cat1 TEXT, cat2 TEXT, cat3 TEXT, sigungu_code TEXT, sigungu_name TEXT, region TEXT,
  addr TEXT, lat REAL, lon REAL, image TEXT, thumb TEXT, overview TEXT,
  homepage TEXT, tel TEXT, modified TEXT, collected_at TEXT);
CREATE INDEX ix_places_sgg ON places(sigungu_name, type_id);
CREATE TABLE festivals(
  contentid TEXT PRIMARY KEY, title TEXT, start_date TEXT, end_date TEXT,
  sigungu_name TEXT, region TEXT, addr TEXT, lat REAL, lon REAL, image TEXT, overview TEXT);
CREATE TABLE visitors_monthly(
  ym TEXT, sigungu_name TEXT, region TEXT, local REAL, outsider REAL, foreigner REAL,
  days INTEGER, PRIMARY KEY(ym, sigungu_name));
CREATE TABLE demand(
  ym TEXT, sigungu_name TEXT, kind TEXT, indicator TEXT, value REAL);
CREATE INDEX ix_demand ON demand(sigungu_name, ym);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
"""


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = html.unescape(s)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"[ \t]+", " ", s).strip()


def load_json(name: str) -> list[dict]:
    return json.loads((RAW / name).read_text(encoding="utf-8"))


def fnum(v) -> float | None:
    try:
        f = float(v)
        return f if f else None
    except (TypeError, ValueError):
        return None


def build() -> None:
    sgg = {s["code"]: s["name"] for s in load_json("sigungu.json")}
    lcls = {}
    for c in load_json("lcls_codes.json"):
        lcls[c["lclsSystm1Cd"]] = c["lclsSystm1Nm"]
        lcls[c["lclsSystm2Cd"]] = c["lclsSystm2Nm"]
        lcls[c["lclsSystm3Cd"]] = c["lclsSystm3Nm"]

    detail_dir = RAW / "detail"
    details = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in detail_dir.glob("*.json")}

    con = sqlite3.connect(TOUR_DB)
    con.executescript(SCHEMA)

    rows = []
    for p in load_json("places_list.json"):
        name = sgg.get(str(p.get("lDongSignguCd")), "")
        d = details.get(str(p["contentid"]), {})
        rows.append((
            str(p["contentid"]), clean_text(p["title"]), str(p["contenttypeid"]),
            CONTENT_TYPES.get(str(p["contenttypeid"]), "기타"),
            lcls.get(p.get("lclsSystm1"), ""), lcls.get(p.get("lclsSystm2"), ""),
            lcls.get(p.get("lclsSystm3"), ""), str(p.get("lDongSignguCd")), name,
            "광주" if name in GWANGJU_GU else "전남",
            " ".join(x for x in [p.get("addr1"), p.get("addr2")] if x),
            fnum(p.get("mapy")), fnum(p.get("mapx")), p.get("firstimage") or "",
            p.get("firstimage2") or "", clean_text(d.get("overview")),
            clean_text(d.get("homepage")), p.get("tel") or "",
            p.get("modifiedtime"), p.get("collected_at")))
    con.executemany(f"INSERT OR REPLACE INTO places VALUES ({','.join('?' * 20)})", rows)

    fest = []
    for f in load_json("festivals.json"):
        name = sgg.get(str(f.get("lDongSignguCd")), "")
        d = details.get(str(f["contentid"]), {})
        fest.append((str(f["contentid"]), clean_text(f["title"]), f.get("eventstartdate"),
                     f.get("eventenddate"), name, "광주" if name in GWANGJU_GU else "전남",
                     f.get("addr1"), fnum(f.get("mapy")), fnum(f.get("mapx")),
                     f.get("firstimage") or "", clean_text(d.get("overview"))))
    con.executemany(f"INSERT OR REPLACE INTO festivals VALUES ({','.join('?' * 11)})", fest)

    # 시군구 중심좌표 = 해당 지역 관광지 좌표 중앙값 (날씨 조회·지도 초기 위치)
    cent = pd.read_sql("SELECT sigungu_code code, lat, lon FROM places WHERE lat IS NOT NULL", con)
    cent = cent.groupby("code").agg(lat=("lat", "median"), lon=("lon", "median"),
                                    n=("lat", "size"))
    con.executemany("INSERT INTO sigungu VALUES (?,?,?,?,?,?)", [
        (code, name, "광주" if name in GWANGJU_GU else "전남",
         float(cent.lat.get(code, 0)) or None, float(cent.lon.get(code, 0)) or None,
         int(cent.n.get(code, 0)))
        for code, name in sgg.items()])

    # 방문자(일별 → 월 합계). 이동통신 기반 '추정' 방문자이며 실제 인원 수와 다를 수 있다.
    v = pd.read_csv(LEGACY / "tourism_visitors.csv")
    v = v[v["구분"] == "시군구"].copy()
    v["ym"] = v["baseYmd"].astype(str).str[:6]
    v["kind"] = v["touDivNm"].map({"현지인(a)": "local", "외지인(b)": "outsider", "외국인(c)": "foreigner"})
    m = (v.pivot_table(index=["ym", "signguNm", "지역"], columns="kind", values="touNum", aggfunc="sum")
          .reset_index())
    days = v.groupby(["ym", "signguNm"]).baseYmd.nunique().rename("days").reset_index()
    m = m.merge(days, on=["ym", "signguNm"])
    con.executemany("INSERT INTO visitors_monthly VALUES (?,?,?,?,?,?,?)",
                    [(r.ym, r.signguNm, r["지역"], r.local, r.outsider, r.foreigner, int(r.days))
                     for _, r in m.iterrows()])

    dem = []
    for file, kind, ind, val in [("tourism_stay_demand.csv", "체류", "tarSjrnDsIxNm", "tarSjrnDsIxVal"),
                                 ("tourism_spend_demand.csv", "소비", "tarExpDsIxNm", "tarExpDsIxVal")]:
        d = pd.read_csv(LEGACY / file)
        d = d[d["signguNm"] != "_"]
        dem += [(str(r.baseYm), r.signguNm, kind, r[ind], float(r[val])) for _, r in d.iterrows()]
    con.executemany("INSERT INTO demand VALUES (?,?,?,?,?)", dem)

    stamp = datetime.now().isoformat(timespec="seconds")
    meta = {
        "built_at": stamp,
        "places_collected_at": rows[0][-1] if rows else "",
        "places": str(len(rows)),
        "overview_filled": str(sum(1 for r in rows if r[15])),
        "festivals": str(len(fest)),
        "visitors_range": f"{m.ym.min()}~{m.ym.max()}",
        "source": "한국관광공사 TourAPI(KorService2)·관광빅데이터 / 공공데이터포털",
    }
    con.executemany("INSERT INTO meta VALUES (?,?)", meta.items())
    con.commit()
    con.close()
    print("tour.db 빌드 완료:", meta)


if __name__ == "__main__":
    build()
