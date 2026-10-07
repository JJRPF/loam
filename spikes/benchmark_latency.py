#!/usr/bin/env python3
"""
Spike (c): Latency Benchmarking for Route Options Generation on Raspberry Pi 5
Benchmarks point-to-point and multi-option routing through GraphHopper on the Pi.
"""

import time
import httpx
import statistics

# Test locations in New Hampshire
# Bear Brook State Park (MTB trail system)
POINTS = [
    {"name": "Bear Brook Trailhead", "lat": 43.1305, "lon": -71.3524},
    {"name": "Bear Hill", "lat": 43.1482, "lon": -71.3651},
    {"name": "Hall Mountain", "lat": 43.1190, "lon": -71.3410},
    {"name": "Catamount Hill", "lat": 43.1412, "lon": -71.3320},
    {"name": "Podunk Road", "lat": 43.1550, "lon": -71.3480},
    {"name": "Broken Ground (Concord)", "lat": 43.2180, "lon": -71.5050},
    {"name": "Franklin Falls Dam", "lat": 43.4680, "lon": -71.6520},
    {"name": "Page Hill (Hill, NH)", "lat": 43.5280, "lon": -71.7150},
    {"name": "Amsden / Weare", "lat": 43.0850, "lon": -71.7250},
    {"name": "Fort Rock (Exeter)", "lat": 42.9820, "lon": -70.9750},
]

def benchmark_graphhopper(base_url: str, label: str):
    print(f"\n==========================================")
    print(f"Benchmarking GraphHopper at {label} ({base_url})")
    print(f"==========================================")
    
    client = httpx.Client(base_url=base_url, timeout=10.0)
    
    # 1. Warm-up
    try:
        resp = client.get("/health")
        print(f"Health check: {resp.status_code} ({resp.text.strip()})")
    except Exception as e:
        print(f"Failed to connect to {base_url}: {e}")
        return None

    # 2. Single-leg point-to-point queries
    p2p_latencies = []
    print("\nRunning 10 distinct point-to-point routes...")
    for i in range(len(POINTS) - 1):
        p1 = POINTS[i]
        p2 = POINTS[i + 1]
        t0 = time.perf_counter()
        r = client.get(
            "/route",
            params={
                "point": [f"{p1['lat']},{p1['lon']}", f"{p2['lat']},{p2['lon']}"],
                "profile": "mtb",
                "details": ["surface", "road_class", "track_type"],
            }
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        p2p_latencies.append(elapsed_ms)
        data = r.json()
        dist_m = data["paths"][0]["distance"] if "paths" in data else 0
        points_count = len(data["paths"][0]["points"]) if "paths" in data else 0
        print(f"  Route {i+1} ({p1['name'][:15]} -> {p2['name'][:15]}): {elapsed_ms:6.1f} ms | {dist_m/1609.34:5.2f} mi | {points_count} pts")

    # 3. Simulate candidate generation for ~10 options (e.g. 20 and 40 candidates with perturbations)
    print("\nSimulating Option Generation (40 candidate routes with waypoints)...")
    origin = POINTS[0]
    dest = POINTS[1]
    
    candidate_latencies = []
    t_batch_start = time.perf_counter()
    for k in range(40):
        # Detour jitter
        jitter_lat = origin["lat"] + (k % 5 - 2) * 0.005
        jitter_lon = origin["lon"] + (k % 4 - 2) * 0.005
        t0 = time.perf_counter()
        r = client.get(
            "/route",
            params={
                "point": [f"{origin['lat']},{origin['lon']}", f"{jitter_lat},{jitter_lon}", f"{dest['lat']},{dest['lon']}"],
                "profile": "mtb",
                "details": ["surface", "road_class"],
            }
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        candidate_latencies.append(elapsed_ms)
    total_batch_time = (time.perf_counter() - t_batch_start) * 1000

    results = {
        "label": label,
        "p2p_min": min(p2p_latencies),
        "p2p_avg": statistics.mean(p2p_latencies),
        "p2p_median": statistics.median(p2p_latencies),
        "p2p_p95": sorted(p2p_latencies)[int(len(p2p_latencies)*0.95)],
        "candidate_avg": statistics.mean(candidate_latencies),
        "batch_40_total_ms": total_batch_time,
        "batch_40_per_cand_ms": total_batch_time / 40,
    }

    print("\n--- Summary ---")
    print(f"P2P Latency: min={results['p2p_min']:.1f}ms, mean={results['p2p_avg']:.1f}ms, median={results['p2p_median']:.1f}ms, p95={results['p2p_p95']:.1f}ms")
    print(f"40 Candidates Generation Batch: {total_batch_time:.1f} ms total ({results['batch_40_per_cand_ms']:.1f} ms per route)")
    return results

if __name__ == "__main__":
    local_res = benchmark_graphhopper("http://localhost:8989", "MacBook Pro M2 (omarchy-mac)")
    pi_res = benchmark_graphhopper("http://192.168.1.111:8989", "Raspberry Pi 5 (core-node)")
