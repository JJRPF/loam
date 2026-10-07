import struct
import datetime
from typing import List, Optional, Dict, Any

FIT_EPOCH = datetime.datetime(1989, 12, 31, 0, 0, 0, tzinfo=datetime.timezone.utc)

def compute_crc(data: bytes, crc: int = 0) -> int:
    crc_table = [
        0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
        0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400
    ]
    for byte in data:
        tmp = crc_table[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ crc_table[byte & 0xF]
        tmp = crc_table[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ crc_table[(byte >> 4) & 0xF]
    return crc

def deg_to_semicircles(deg: float) -> int:
    # Semicircles: degrees * (2^31 / 180)
    return int(deg * (2147483648.0 / 180.0))

def to_fit_timestamp(dt: datetime.datetime) -> int:
    return int((dt - FIT_EPOCH).total_seconds())

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0)**2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

def build_fit_course(
    name: str,
    sport: str, # 'mtb', 'bike', 'trail_run', etc.
    coordinates: List[List[float]], # [[lon, lat], ...] or [[lon, lat, ele], ...]
    distance_miles: float,
    duration_minutes: float,
    elevation_gain_ft: float = 0.0,
    elevation_loss_ft: float = 0.0,
    start_time: Optional[datetime.datetime] = None
) -> bytes:
    """
    Builds a binary Garmin FIT Course file (.fit) compliant with Garmin fenix 7 Pro
    and Garmin Edge/Forerunner devices.
    """
    if start_time is None:
        start_time = datetime.datetime.now(datetime.timezone.utc)
    elif start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=datetime.timezone.utc)

    fit_start_ts = to_fit_timestamp(start_time)

    # FIT sport enum: 2 = cycling, 1 = running
    fit_sport = 1 if "run" in sport.lower() or "foot" in sport.lower() else 2

    total_dist_m = distance_miles * 1609.344
    total_time_s = max(duration_minutes * 60.0, 1.0)
    ascent_m = int(round(elevation_gain_ft * 0.3048))
    descent_m = int(round(elevation_loss_ft * 0.3048))

    body = bytearray()

    # 1. Definition Message: file_id (Global Msg 0, Local 0)
    body.append(0x40 | 0) # Def local 0
    body.append(0) # Reserved
    body.append(0) # Architecture: Little Endian
    body.extend(struct.pack('<H', 0)) # Global Msg 0 (file_id)
    body.append(5) # 5 fields
    body.extend([0, 1, 0])    # type (enum)
    body.extend([1, 2, 132])  # manufacturer (uint16)
    body.extend([2, 2, 132])  # product (uint16)
    body.extend([3, 4, 140])  # serial_number (uint32z)
    body.extend([4, 4, 134])  # time_created (uint32)

    # Data Message: file_id
    body.append(0) # Local 0
    body.append(6) # Type: course (6)
    body.extend(struct.pack('<H', 1)) # Manufacturer: Garmin (1)
    body.extend(struct.pack('<H', 0)) # Product: 0
    body.extend(struct.pack('<I', 0x5452414C)) # Serial: 'TRAL'
    body.extend(struct.pack('<I', fit_start_ts))

    # 2. Definition Message: course (Global Msg 31, Local 1)
    body.append(0x40 | 1) # Def local 1
    body.append(0)
    body.append(0)
    body.extend(struct.pack('<H', 31)) # Global Msg 31 (course)
    body.append(2) # 2 fields
    body.extend([4, 1, 0]) # sport (enum)
    name_len = 32
    body.extend([5, name_len, 7]) # name (string)

    # Data Message: course
    body.append(1) # Local 1
    body.append(fit_sport)
    encoded_name = (name or "Loam Route").encode("utf-8")[:name_len - 1].ljust(name_len, b'\x00')
    body.extend(encoded_name)

    # 3. Definition Message: lap (Global Msg 19, Local 2)
    body.append(0x40 | 2) # Def local 2
    body.append(0)
    body.append(0)
    body.extend(struct.pack('<H', 19)) # Global Msg 19 (lap)
    body.append(9) # 9 fields
    body.extend([253, 4, 134]) # timestamp (uint32)
    body.extend([2, 4, 134])   # start_time (uint32)
    body.extend([3, 4, 133])   # start_position_lat (sint32)
    body.extend([4, 4, 133])   # start_position_long (sint32)
    body.extend([7, 4, 134])   # total_elapsed_time (uint32, scale 1000)
    body.extend([8, 4, 134])   # total_timer_time (uint32, scale 1000)
    body.extend([9, 4, 134])   # total_distance (uint32, scale 100)
    body.extend([21, 2, 132])  # total_ascent (uint16)
    body.extend([22, 2, 132])  # total_descent (uint16)

    first_lat = coordinates[0][1] if coordinates else 43.13
    first_lon = coordinates[0][0] if coordinates else -71.35
    lap_end_ts = fit_start_ts + int(total_time_s)

    # Data Message: lap
    body.append(2) # Local 2
    body.extend(struct.pack('<I', lap_end_ts))
    body.extend(struct.pack('<I', fit_start_ts))
    body.extend(struct.pack('<i', deg_to_semicircles(first_lat)))
    body.extend(struct.pack('<i', deg_to_semicircles(first_lon)))
    body.extend(struct.pack('<I', int(total_time_s * 1000)))
    body.extend(struct.pack('<I', int(total_time_s * 1000)))
    body.extend(struct.pack('<I', int(total_dist_m * 100)))
    body.extend(struct.pack('<H', min(ascent_m, 65535)))
    body.extend(struct.pack('<H', min(descent_m, 65535)))

    # 4. Definition Message: record (Global Msg 20, Local 3)
    body.append(0x40 | 3) # Def local 3
    body.append(0)
    body.append(0)
    body.extend(struct.pack('<H', 20)) # Global Msg 20 (record)
    body.append(5) # 5 fields
    body.extend([253, 4, 134]) # timestamp (uint32)
    body.extend([0, 4, 133])   # position_lat (sint32)
    body.extend([1, 4, 133])   # position_long (sint32)
    body.extend([5, 4, 134])   # distance (uint32, scale 100)
    body.extend([2, 2, 132])   # altitude (uint16, scale 5, offset 500)

    # Calculate cumulative distance along coordinates
    cum_distances = [0.0]
    total_calc_dist = 0.0
    for i in range(1, len(coordinates)):
        seg_dist = haversine_m(
            coordinates[i - 1][1], coordinates[i - 1][0],
            coordinates[i][1], coordinates[i][0]
        )
        total_calc_dist += seg_dist
        cum_distances.append(total_calc_dist)

    scale_dist = total_dist_m / max(total_calc_dist, 1.0) if total_calc_dist > 0 else 1.0
    num_pts = len(coordinates)

    # Write Data Messages: record
    for i, pt in enumerate(coordinates):
        lon = pt[0]
        lat = pt[1]
        ele = pt[2] if len(pt) > 2 else 150.0 # meters

        # Interpolate timestamp and distance
        dist_m = cum_distances[i] * scale_dist
        progress = dist_m / max(total_dist_m, 1.0)
        pt_ts = fit_start_ts + int(progress * total_time_s)

        alt_raw = int(round((ele + 500.0) * 5.0))
        alt_raw = max(0, min(alt_raw, 65535))

        body.append(3) # Local 3
        body.extend(struct.pack('<I', pt_ts))
        body.extend(struct.pack('<i', deg_to_semicircles(lat)))
        body.extend(struct.pack('<i', deg_to_semicircles(lon)))
        body.extend(struct.pack('<I', int(dist_m * 100)))
        body.extend(struct.pack('<H', alt_raw))

    # Construct 14-byte File Header
    hdr = bytearray([14, 0x20, 0x08, 0x08])
    hdr.extend(struct.pack('<I', len(body)))
    hdr.extend(b'.FIT')
    hdr_crc = compute_crc(bytes(hdr[:12]))
    hdr.extend(struct.pack('<H', hdr_crc))

    # Compute full file CRC16
    full_file = hdr + body
    file_crc = compute_crc(bytes(full_file))
    full_file.extend(struct.pack('<H', file_crc))

    return bytes(full_file)
