#!/usr/bin/env python3
"""Strip a Garmin account export down to privacy-filtered GPS tracks (docs/round7-plan.md 7.1).

Runs on the owner's own machine only. Reads the summarized activities, selects trail sports,
streams the uploaded FIT files out of their zips (never extracting the archive), and keeps only
(lat, lon, time) per record: no heart rate, power, device or profile fields. Each track is
trimmed 0.2 mi at each end and clipped by the owner's privacy zones (app/privacy.py), and
dropped if under 0.5 mi afterwards. Whether a ride was a loop (start and end within 300 m
before trimming) is kept as a boolean only; the start point itself is never stored.

Writes one JSON per activity plus manifest.json to --out (keep it under DATA_DIR, never in
git). Uploads nothing. Run with `python3 -I` from outside the export folder:

    python3 -I scripts/strip_garmin_export.py --export ~/Downloads/<export> \\
        --out ~/dev/loam/main/data/garmin-stripped/ [--privacy-zones zones.json] [--dem-check]
"""
import argparse
import collections
import datetime
import glob
import io
import json
import math
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.activity_parser import TrackPoint  # noqa: E402
from app.privacy import apply_privacy_filters, haversine_m  # noqa: E402

SPORT_BY_TYPE = {
    "mountain_biking": "mtb", "e_bike_mountain": "mtb",
    "cycling": "gravel", "e_bike_fitness": "gravel",
    "trail_running": "trail_run", "running": "trail_run", "hiking": "trail_run", "walking": "trail_run",
}
FIT_SPORT_GROUP = {"cycling": "bike", "e_biking": "bike", "running": "foot", "walking": "foot",
                   "hiking": "foot", "training": None, "generic": None}
GROUP = {"mtb": "bike", "gravel": "bike", "trail_run": "foot"}
MATCH_WINDOW_S = 90
MIN_MILES = 0.5
LOOP_CLOSE_M = 300.0
SEMICIRCLE = 180.0 / 2 ** 31


def load_activities(export):
    acts = []
    for f in sorted(glob.glob(os.path.join(export, "DI_CONNECT", "DI-Connect-Fitness", "*_summarizedActivities.json"))):
        with open(f) as fh:
            for block in json.load(fh):
                acts.extend(block.get("summarizedActivitiesExport", []))
    return acts


def load_zones(path):
    if not path:
        return []
    with open(path) as fh:
        zones = json.load(fh)
    return [{"lat": float(z["lat"]), "lon": float(z["lon"]), "radius_m": float(z.get("radius_m", 320.0))} for z in zones]


def read_fit(data):
    """(file type, start time, sport group, [(lat, lon, time)]) of a FIT file; None when unreadable."""
    import fitparse

    try:
        ff = fitparse.FitFile(io.BytesIO(data), check_crc=False)
        fid = next(ff.get_messages("file_id"), None)
        if fid is None or fid.get_value("type") != "activity":
            return None
        pts, sport = [], None
        for msg in ff.get_messages(["record", "session"]):
            if msg.name == "session":
                sport = FIT_SPORT_GROUP.get(str(msg.get_value("sport")), sport)
                continue
            lat, lon, t = msg.get_value("position_lat"), msg.get_value("position_long"), msg.get_value("timestamp")
            if lat is None or lon is None or t is None:
                continue
            lat, lon = lat * SEMICIRCLE, lon * SEMICIRCLE
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                pts.append((lat, lon, t.replace(tzinfo=datetime.timezone.utc)))
        if not pts:
            return None
        return pts[0][2], sport, pts
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--privacy-zones", help="JSON list of {lat, lon, radius_m}, kept outside the repo")
    ap.add_argument("--dem-check", action="store_true",
                    help="compare DEM gain with Garmin's elevationCorrected gain (prints numbers only)")
    args = ap.parse_args()

    export = os.path.abspath(os.path.expanduser(args.export))
    out = os.path.abspath(os.path.expanduser(args.out))
    if out.startswith(export):
        sys.exit("--out must be outside the export folder")
    os.makedirs(out, exist_ok=True)
    zones = load_zones(args.privacy_zones)

    acts = load_activities(export)
    skipped = collections.Counter()
    selected = []
    for a in acts:
        sport = SPORT_BY_TYPE.get(a.get("activityType"))
        if sport is None:
            skipped[f"type:{a.get('activityType')}"] += 1
            continue
        if a.get("startLatitude") is None:
            skipped["no GPS start in summary"] += 1
            continue
        selected.append({"id": a["activityId"], "sport": sport, "start": a["startTimeGmt"] / 1000.0,
                         "elevationCorrected": a.get("elevationCorrected"), "elevationGain": a.get("elevationGain")})
    by_start = sorted(selected, key=lambda s: s["start"])
    starts = [s["start"] for s in by_start]
    print(f"{len(acts)} activities; {len(selected)} selected trail activities with GPS", file=sys.stderr)

    import bisect
    matched = {}
    files_seen = files_activity = 0
    for z in sorted(glob.glob(os.path.join(export, "DI_CONNECT", "DI-Connect-Uploaded-Files", "*.zip"))):
        with zipfile.ZipFile(z) as zf:
            for info in zf.infolist():
                if not info.filename.lower().endswith(".fit") or info.file_size > 50 * 1024 * 1024:
                    continue
                files_seen += 1
                res = read_fit(zf.read(info))
                if res is None:
                    continue
                files_activity += 1
                t0, group, pts = res
                ts = t0.timestamp()
                i = bisect.bisect_left(starts, ts - MATCH_WINDOW_S)
                best = None
                while i < len(starts) and starts[i] <= ts + MATCH_WINDOW_S:
                    cand = by_start[i]
                    if group in (None, GROUP[cand["sport"]]) and cand["id"] not in matched:
                        if best is None or abs(cand["start"] - ts) < abs(best["start"] - ts):
                            best = cand
                    i += 1
                if best is not None:
                    matched[best["id"]] = (best, pts)
    print(f"{files_seen} FIT files read, {files_activity} GPS activity files, {len(matched)} matched", file=sys.stderr)

    manifest = {"created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "by_sport_year": {}, "written": 0, "loops": 0, "skipped": {}}
    dem_rows = []
    for sel in selected:
        if sel["id"] not in matched:
            skipped["no matching GPS file"] += 1
            continue
        _, pts = matched[sel["id"]]
        is_loop = haversine_m(pts[0][1], pts[0][0], pts[-1][1], pts[-1][0]) <= LOOP_CLOSE_M
        if args.dem_check and sel.get("elevationCorrected") and sel.get("elevationGain"):
            from app.elevation import route_elevation
            _, gain_m, _ = route_elevation([[p[1], p[0]] for p in pts])
            if gain_m is not None:
                dem_rows.append((sel["elevationGain"] / 100.0, gain_m))  # summaries store centimeters
        track = [TrackPoint(lat=p[0], lon=p[1], ele=None, time=p[2]) for p in pts]
        kept, stats = apply_privacy_filters(track, zones)
        miles = sum(haversine_m(kept[i].lon, kept[i].lat, kept[i + 1].lon, kept[i + 1].lat)
                    for i in range(len(kept) - 1)) / 1609.344 if len(kept) > 1 else 0.0
        if stats.get("is_empty") or miles < MIN_MILES:
            skipped["under 0.5 mi after trimming and privacy zones"] += 1
            continue
        start = datetime.datetime.fromtimestamp(sel["start"], datetime.timezone.utc)
        record = {
            "activity_id": str(sel["id"]),
            "sport": sel["sport"],
            "start_time": start.isoformat(),
            "is_loop": is_loop,
            "points": [[round(p.lat, 6), round(p.lon, 6), int(p.time.timestamp())] for p in kept],
        }
        with open(os.path.join(out, f"{sel['id']}.json"), "w") as fh:
            json.dump(record, fh, separators=(",", ":"))
        key = f"{sel['sport']}:{start.year}"
        manifest["by_sport_year"][key] = manifest["by_sport_year"].get(key, 0) + 1
        manifest["written"] += 1
        manifest["loops"] += int(is_loop)
    manifest["skipped"] = dict(skipped)
    manifest["fit_files_read"] = files_seen
    manifest["gps_activity_files"] = files_activity
    with open(os.path.join(out, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    print(json.dumps(manifest, indent=1, sort_keys=True))
    if dem_rows:
        diffs = sorted(abs(d - g) / g * 100.0 for g, d in dem_rows if g > 0)
        within = sum(1 for x in diffs if x <= 15.0)
        print(f"DEM check: {len(diffs)} elevation-corrected activities; |DEM - Garmin| / Garmin: "
              f"median {diffs[len(diffs) // 2]:.1f}%, within 15%: {within}/{len(diffs)}")


if __name__ == "__main__":
    main()
