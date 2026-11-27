"""거리 계산과 동선 정렬 (Haversine + 가까운 곳 먼저 방문)."""
from __future__ import annotations

import math

EARTH_KM = 6371.0


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 좌표 사이 직선 거리(km). 실제 도로 거리보다 짧다."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def order_route(stops: list[dict], start: tuple[float, float] | None = None) -> list[dict]:
    """가장 가까운 곳부터 차례로 방문하는 순서(Nearest Neighbor)."""
    if len(stops) <= 1:
        return list(stops)
    rest = list(stops)
    if start is None:
        cur = rest.pop(0)
    else:
        cur = min(rest, key=lambda s: haversine(start[0], start[1], s["lat"], s["lon"]))
        rest.remove(cur)
    route = [cur]
    while rest:
        nxt = min(rest, key=lambda s: haversine(cur["lat"], cur["lon"], s["lat"], s["lon"]))
        rest.remove(nxt)
        route.append(nxt)
        cur = nxt
    return route


def route_km(stops: list[dict]) -> float:
    return sum(haversine(a["lat"], a["lon"], b["lat"], b["lon"]) for a, b in zip(stops, stops[1:]))


def drive_minutes(km: float) -> int:
    """직선거리 × 1.4(도로 우회) ÷ 평균 40km/h 로 어림한 이동 시간."""
    return round(km * 1.4 / 40 * 60)
