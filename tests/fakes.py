"""Test doubles for third-party services. Test-only: production code has no offline paths.

`FakeGarmin` replaces `garminconnect.Garmin` (see the autouse fixture in conftest.py) so the
connector's real code runs without network access. Its activities' GPS tracks are real
GraphHopper routes on the local stack, so map-matching has something real to match.
"""
import json

import httpx

from app.config import settings

MFA_CODE = "654321"


def _gh_route_points(a, b):
    """lat/lon points of a local GraphHopper route between two (lat, lon) points, or []."""
    try:
        resp = httpx.get(
            f"{settings.graphhopper_url}/route",
            params={"point": [f"{a[0]},{a[1]}", f"{b[0]},{b[1]}"], "profile": "mtb", "points_encoded": "false"},
            timeout=10.0,
        )
        coords = resp.json()["paths"][0]["points"]["coordinates"]
        return [(lat, lon) for lon, lat in coords]
    except Exception:
        return []


def _gpx(points, start="2026-09-01T14:00:00Z"):
    import datetime

    t0 = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
    rows = []
    for i, (lat, lon) in enumerate(points):
        t = (t0 + datetime.timedelta(seconds=5 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append(f'<trkpt lat="{lat:.6f}" lon="{lon:.6f}"><time>{t}</time></trkpt>')
    return ('<?xml version="1.0"?><gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
            f'<trk><trkseg>{"".join(rows)}</trkseg></trk></gpx>').encode()


# Two rides between public points in Bear Brook State Park, plus a gym session that must be filtered.
FAKE_ACTIVITIES = [
    {"activityId": 9001, "activityName": "Test ride 1", "activityType": {"typeKey": "mountain_biking"},
     "hasPolyline": True, "startLatitude": 43.1349, "startLongitude": -71.3659, "distance": 6000.0,
     "duration": 1800.0, "startTimeGMT": "2026-09-01T14:00:00", "_route": ((43.1349, -71.3659), (43.1500, -71.3420))},
    {"activityId": 9002, "activityName": "Test ride 2", "activityType": {"typeKey": "mountain_biking"},
     "hasPolyline": True, "startLatitude": 43.1500, "startLongitude": -71.3420, "distance": 6000.0,
     "duration": 1900.0, "startTimeGMT": "2026-09-03T14:00:00", "_route": ((43.1500, -71.3420), (43.1349, -71.3659))},
    {"activityId": 9003, "activityName": "Gym", "activityType": {"typeKey": "strength_training"},
     "hasPolyline": False, "distance": 0.0, "duration": 1800.0, "startTimeGMT": "2026-09-02T14:00:00"},
]


class _FakeGarthClient:
    def dumps(self):
        return json.dumps({"di_token": "test-di-token", "oauth2": "test"})


class FakeGarmin:
    class ActivityDownloadFormat:
        GPX = "gpx"

    def __init__(self, email=None, password=None, return_on_mfa=False, **_):
        self.email = email
        self.password = password
        self.client = _FakeGarthClient()

    def login(self, tokenstore=None):
        if tokenstore:
            return None, None
        if self.password == "wrong-password":
            raise RuntimeError("401 Unauthorized")
        if (self.email or "").startswith("mfa"):
            return "needs_mfa", None
        return None, None

    def resume_login(self, _state, code):
        if code != MFA_CODE:
            raise RuntimeError("Invalid MFA code")

    def get_activities(self, start, limit):
        return [{k: v for k, v in a.items() if not k.startswith("_")} for a in FAKE_ACTIVITIES[start:start + limit]]

    def download_activity(self, activity_id, dl_fmt=None):
        act = next(a for a in FAKE_ACTIVITIES if str(a["activityId"]) == str(activity_id))
        if "_route" not in act:
            return b""
        return _gpx(_gh_route_points(*act["_route"]), start=act["startTimeGMT"] + "Z")
