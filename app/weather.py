"""Hourly forecast for a point from the US National Weather Service (api.weather.gov, no key).

Only the rounded query point (0.1 degree, about 11 km) is sent upstream, and results are cached
for 15 minutes. When the service can't answer, callers get None; no forecast is ever invented.
"""
import time
from typing import Any, Dict, Optional

import httpx

from app.config import settings

NWS = "https://api.weather.gov"
HEADERS = {"User-Agent": settings.user_agent, "Accept": "application/geo+json"}
TTL_S = 900  # minimum; the forecast response's own Cache-Control max-age is honoured up to MAX_TTL_S
MAX_TTL_S = 3600
_cache: Dict[tuple, tuple] = {}


def _ttl(resp: httpx.Response) -> float:
    """Cache lifetime from the response's Cache-Control max-age, within [TTL_S, MAX_TTL_S]."""
    for part in resp.headers.get("cache-control", "").split(","):
        part = part.strip().lower()
        if part.startswith("max-age="):
            try:
                return float(min(MAX_TTL_S, max(TTL_S, int(part[8:]))))
            except ValueError:
                break
    return float(TTL_S)


def _shape(data: Dict[str, Any], hours: int) -> Dict[str, Any]:
    periods = []
    for p in (data.get("properties", {}).get("periods") or [])[:hours]:
        precip = (p.get("probabilityOfPrecipitation") or {}).get("value")
        periods.append({
            "start": p.get("startTime"),
            "temp_f": p.get("temperature") if p.get("temperatureUnit") == "F" else None,
            "precip_pct": precip,
            "wind": p.get("windSpeed"),
            "summary": p.get("shortForecast"),
        })
    return {"source": "National Weather Service", "periods": periods}


async def hourly_forecast(lat: float, lon: float, hours: int = 12, client: Optional[httpx.AsyncClient] = None) -> Optional[Dict[str, Any]]:
    key = (round(lat, 1), round(lon, 1), hours)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < hit[2]:
        return hit[1]
    own = client is None
    client = client or httpx.AsyncClient(timeout=10.0, headers=HEADERS, follow_redirects=True)
    try:
        meta = await client.get(f"{NWS}/points/{key[0]:.1f},{key[1]:.1f}")
        if meta.status_code != 200:
            return None
        url = meta.json()["properties"]["forecastHourly"]
        fc = await client.get(url)
        if fc.status_code != 200:
            return None
        out = _shape(fc.json(), hours)
        if not out["periods"]:
            return None
        _cache[key] = (time.time(), out, _ttl(fc))
        return out
    except Exception:
        return None
    finally:
        if own:
            await client.aclose()
