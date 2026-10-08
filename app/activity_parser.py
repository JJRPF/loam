import datetime
from dataclasses import dataclass
from typing import List, Optional, Tuple
import defusedxml.ElementTree as ET
import fitparse

SEMICIRCLE_FACTOR = 180.0 / (2 ** 31)
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB

@dataclass
class TrackPoint:
    lat: float
    lon: float
    ele: Optional[float] = 0.0
    time: Optional[datetime.datetime] = None

def parse_iso_time(time_str: str) -> Optional[datetime.datetime]:
    if not time_str:
        return None
    try:
        # Handle 'Z' or standard offsets
        clean_str = time_str.strip().replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(clean_str)
    except Exception:
        return None

def parse_gpx_content(xml_bytes: bytes) -> Tuple[List[TrackPoint], str, Optional[datetime.datetime]]:
    """
    Defensively parses GPX XML bytes using defusedxml to block XXE attacks and entity expansions.
    """
    if len(xml_bytes) > MAX_FILE_SIZE:
        raise ValueError(f"File size exceeds maximum allowed limit of {MAX_FILE_SIZE // (1024*1024)} MB.")

    try:
        root = ET.fromstring(xml_bytes)
    except Exception as e:
        raise ValueError(f"Invalid or malformed GPX XML: {e}")

    # Remove namespace if present
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    detected_sport = "mtb"
    activity_time = None

    # Check metadata time
    meta_time = root.find(f".//{ns}metadata/{ns}time")
    if meta_time is not None and meta_time.text:
        activity_time = parse_iso_time(meta_time.text)

    # Check trk type
    trk_type = root.find(f".//{ns}trk/{ns}type")
    if trk_type is not None and trk_type.text:
        t_lower = trk_type.text.lower()
        if "run" in t_lower or "foot" in t_lower or "hike" in t_lower:
            detected_sport = "trail_run"
        elif "gravel" in t_lower:
            detected_sport = "mtb_gravel"
        elif "bike" in t_lower or "cycle" in t_lower or "mtb" in t_lower:
            detected_sport = "mtb"

    trackpoints: List[TrackPoint] = []
    for trkpt in root.findall(f".//{ns}trkpt"):
        try:
            lat = float(trkpt.attrib["lat"])
            lon = float(trkpt.attrib["lon"])
        except (KeyError, ValueError):
            continue

        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue

        ele = 0.0
        ele_elem = trkpt.find(f"{ns}ele")
        if ele_elem is not None and ele_elem.text:
            try:
                ele = float(ele_elem.text)
            except ValueError:
                ele = 0.0

        pt_time = None
        time_elem = trkpt.find(f"{ns}time")
        if time_elem is not None and time_elem.text:
            pt_time = parse_iso_time(time_elem.text)
            if activity_time is None and pt_time is not None:
                activity_time = pt_time

        trackpoints.append(TrackPoint(lat=lat, lon=lon, ele=ele, time=pt_time))

    if not trackpoints:
        raise ValueError("No valid GPS trackpoints found in GPX file.")

    return trackpoints, detected_sport, activity_time

def parse_fit_content(fit_bytes: bytes) -> Tuple[List[TrackPoint], str, Optional[datetime.datetime]]:
    """
    Parses Garmin FIT binary file bytes safely into trackpoints.
    """
    if len(fit_bytes) > MAX_FILE_SIZE:
        raise ValueError(f"File size exceeds maximum allowed limit of {MAX_FILE_SIZE // (1024*1024)} MB.")

    try:
        fitfile = fitparse.FitFile(fit_bytes)
    except Exception as e:
        raise ValueError(f"Invalid or corrupted FIT file: {e}")

    detected_sport = "mtb"
    activity_time = None
    trackpoints: List[TrackPoint] = []

    # Detect sport from sport/session messages if present
    for record in fitfile.get_messages("sport"):
        values = record.get_values()
        s_name = str(values.get("sport") or values.get("sub_sport") or "").lower()
        if "running" in s_name or "trail" in s_name or "hiking" in s_name:
            detected_sport = "trail_run"
        elif "cycling" in s_name or "biking" in s_name:
            detected_sport = "mtb"

    # Extract record coordinates
    for record in fitfile.get_messages("record"):
        values = record.get_values()
        raw_lat = values.get("position_lat")
        raw_lon = values.get("position_long")

        if raw_lat is None or raw_lon is None:
            continue

        try:
            lat = float(raw_lat) * SEMICIRCLE_FACTOR
            lon = float(raw_lon) * SEMICIRCLE_FACTOR
        except Exception:
            continue

        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue

        ele = values.get("enhanced_altitude") or values.get("altitude") or 0.0
        try:
            ele = float(ele)
        except Exception:
            ele = 0.0

        ts = values.get("timestamp")
        if isinstance(ts, datetime.datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=datetime.timezone.utc)
            if activity_time is None:
                activity_time = ts
        else:
            ts = None

        trackpoints.append(TrackPoint(lat=lat, lon=lon, ele=ele, time=ts))

    if not trackpoints:
        raise ValueError("No valid GPS records found in FIT file.")

    return trackpoints, detected_sport, activity_time

def parse_activity_file(
    content_bytes: bytes,
    filename: str,
    max_size_bytes: int = MAX_FILE_SIZE
) -> Tuple[List[TrackPoint], str, Optional[datetime.datetime]]:
    """
    Auto-detects GPX or FIT format, validates file size, and parses trackpoints defensively.
    """
    if len(content_bytes) > max_size_bytes:
        raise ValueError(f"File size exceeds maximum limit of {max_size_bytes // (1024*1024)} MB.")

    fname_lower = filename.lower().strip()
    if fname_lower.endswith(".fit") or content_bytes[:14].endswith(b".FIT") or (len(content_bytes) > 12 and content_bytes[8:12] == b".FIT"):
        return parse_fit_content(content_bytes)
    elif fname_lower.endswith(".gpx") or b"<gpx" in content_bytes[:1000] or b"<?xml" in content_bytes[:100]:
        return parse_gpx_content(content_bytes)
    else:
        # Try GPX first, then FIT fallback
        try:
            return parse_gpx_content(content_bytes)
        except Exception:
            return parse_fit_content(content_bytes)
