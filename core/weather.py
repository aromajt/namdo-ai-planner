"""날씨 도구: Open-Meteo 무료 API (키 불필요, 최대 16일 예보).

여행일이 예보 범위를 벗어나면 '예보 없음'을 돌려준다 — 날씨를 지어내지 않는다.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache

import requests

WMO = {0: "맑음", 1: "대체로 맑음", 2: "구름 조금", 3: "흐림", 45: "안개", 48: "안개",
       51: "약한 이슬비", 53: "이슬비", 55: "강한 이슬비", 61: "약한 비", 63: "비", 65: "강한 비",
       71: "약한 눈", 73: "눈", 75: "강한 눈", 80: "소나기", 81: "소나기", 82: "강한 소나기",
       95: "뇌우", 96: "뇌우·우박", 99: "뇌우·우박"}
RAINY = {51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99, 71, 73, 75}


@lru_cache(maxsize=128)
def _fetch(lat: float, lon: float) -> dict:
    r = requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": round(lat, 3), "longitude": round(lon, 3), "timezone": "Asia/Seoul",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "forecast_days": 16}, timeout=10)
    r.raise_for_status()
    return r.json()["daily"]


def forecast(lat: float, lon: float, start: date, days: int) -> list[dict]:
    try:
        d = _fetch(lat, lon)
    except Exception as e:  # 네트워크 장애 → 일정 생성은 계속
        return [{"date": str(start), "summary": f"예보 조회 실패({type(e).__name__})", "rainy": False}]
    out = []
    for i in range(days):
        day = date.fromordinal(start.toordinal() + i).isoformat()
        if day not in d["time"]:
            out.append({"date": day, "summary": "예보 범위 밖(16일 이후) - 출발 전 확인 필요", "rainy": False})
            continue
        k = d["time"].index(day)
        code = d["weather_code"][k]
        out.append({
            "date": day, "code": code, "summary": WMO.get(code, f"코드 {code}"),
            "tmax": d["temperature_2m_max"][k], "tmin": d["temperature_2m_min"][k],
            "rain_prob": d["precipitation_probability_max"][k],
            "rainy": code in RAINY or (d["precipitation_probability_max"][k] or 0) >= 60,
        })
    return out
