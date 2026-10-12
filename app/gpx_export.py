import datetime
import html
from typing import List, Optional, Dict, Any

def build_gpx_track(
    name: str,
    sport: str,
    coordinates: List[List[float]], # [[lon, lat], ...] or [[lon, lat, ele], ...]
    distance_miles: float,
    duration_minutes: float,
    elevation_gain_ft: Optional[float] = None,
    elevation_loss_ft: Optional[float] = None,
    waypoints: Optional[List[Dict[str, Any]]] = None,
    start_time: Optional[datetime.datetime] = None
) -> str:
    """
    Builds a standard GPX 1.1 XML string formatted for Garmin Connect, Garmin watches (fenix 7 Pro),
    and outdoor GPS units.
    """
    if start_time is None:
        start_time = datetime.datetime.now(datetime.timezone.utc)
    elif start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=datetime.timezone.utc)

    iso_start = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    clean_name = html.escape(name or "Loam Route")
    total_time_s = max(duration_minutes * 60.0, 1.0)
    num_pts = max(len(coordinates), 1)

    if elevation_gain_ft is not None and elevation_loss_ft is not None:
        elevation_text = f"+{int(round(elevation_gain_ft))} ft / -{int(round(elevation_loss_ft))} ft"
    else:
        elevation_text = "elevation unavailable"

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="Loam Trail Route Builder (https://github.com/JJRPF/loam)"',
        '  xmlns="http://www.topografix.com/GPX/1/1"',
        '  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
        '  xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd">',
        '  <metadata>',
        f'    <name>{clean_name}</name>',
        f'    <desc>Loam Route: {distance_miles:.1f} mi, {elevation_text} ({sport})</desc>',
        f'    <time>{iso_start}</time>',
        '  </metadata>'
    ]

    # Add Waypoints if available
    if waypoints:
        for wp in waypoints:
            lat = wp.get("lat")
            lon = wp.get("lon")
            wp_name = html.escape(wp.get("name", "Waypoint"))
            if lat is not None and lon is not None:
                lines.append(f'  <wpt lat="{lat:.6f}" lon="{lon:.6f}">')
                lines.append(f'    <name>{wp_name}</name>')
                lines.append('  </wpt>')

    # Add Track
    lines.append('  <trk>')
    lines.append(f'    <name>{clean_name}</name>')
    lines.append(f'    <type>{html.escape(sport)}</type>')
    lines.append('    <trkseg>')

    for i, pt in enumerate(coordinates):
        lon = pt[0]
        lat = pt[1]
        ele = pt[2] if len(pt) > 2 else None

        # Timestamp interpolation
        progress = i / max(num_pts - 1, 1)
        pt_dt = start_time + datetime.timedelta(seconds=int(progress * total_time_s))
        pt_iso = pt_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        lines.append(f'      <trkpt lat="{lat:.6f}" lon="{lon:.6f}">')
        if ele is not None:
            lines.append(f'        <ele>{ele:.1f}</ele>')
        lines.append(f'        <time>{pt_iso}</time>')
        lines.append('      </trkpt>')

    lines.append('    </trkseg>')
    lines.append('  </trk>')
    lines.append('</gpx>')

    return "\n".join(lines)
