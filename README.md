# Loam (Trail Route Builder)

A specialized route builder for mountain biking and trail running featuring terrain-mix control, a 12-month recency heat layer to eliminate overgrown ghost trails, and multi-candidate route ranking.

## Stage 1: Foundation and Spikes (Completed)

This repository contains the foundation and technical spikes for the Loam platform:
- **Routing Engine**: GraphHopper 11.1 running on ARM64 (Apple Silicon Mac & Raspberry Pi 5).
- **Spatial Database**: PostgreSQL 18 with PostGIS 3.6 and pgRouting.
- **Base Map Extract**: New Hampshire OpenStreetMap extract (Geofabrik).
- **Backend API**: Python / FastAPI point-to-point routing skeleton with automatic surface-strip categorization (`singletrack`, `doubletrack`, `gravel`, `paved`), imperial unit conversions (miles/feet), and heat integration.
- **Spikes Documentation**: Written conclusions in [docs/spikes-report.md](docs/spikes-report.md).

---

## Technical Spike Conclusions

### 1. Spike (a): Nightly Heat in Router
- **Conclusion**: Feasible via **Hybrid Nightly Re-import + PostGIS Scoring**.
- **Benchmark**: GraphHopper re-import on the Raspberry Pi 5 takes **32.5 seconds** and uses **959 MB RAM** for the entire state of New Hampshire (881k ways).
- **Strategy**: Nightly cron job on the Pi updates `edge_heat` in PostGIS, writes ghost trail exclusions/encoded values, and triggers a 35s GraphHopper re-import with zero downtime. Real-time query ranking applies candidate-level heat scoring.

### 2. Spike (b): Elevation Source Selection
- **Conclusion**: **USGS 3DEP (1/3 arc-second ~ 10m)** selected over SRTM.
- **Rationale**: SRTM (30m/90m) flattens rolling trail climbs by 15–25% or generates artificial cliff-edge spikes. 10m USGS 3DEP accurately models trail switchbacks and punchy climbing.
- **Strategy**: GraphHopper provides slope heuristics, while the Loam API layer enriches route polylines with 10m USGS 3DEP for precision elevation profiles, climb stats, and surface strip cross-sections.

### 3. Spike (c): Latency for ~10 Options on Raspberry Pi 5
- **Conclusion**: **Exceeds requirements by 8x**.
- **Benchmark**:
  - Single point-to-point query on Pi 5: **16.7 ms – 33.7 ms** median.
  - Full batch of 40 candidate routes with detour waypoints: **1,038 ms (~1.04 s)** total.
  - End-to-end latency for 10 deduplicated, scored options: **~1.2 – 1.5 seconds** on the Pi 5 (well under the 10-second budget).

---

## Quickstart

### Prerequisites
- Docker & Docker Compose
- Python 3.12+ (or 3.14)

### Running Locally with Docker Compose
```bash
# 1. Start GraphHopper, PostGIS, and FastAPI API
docker compose up -d

# 2. Check service health
curl http://localhost:8080/health
```

### Running Locally with Python Virtual Environment
```bash
# 1. Activate venv
source .venv/bin/activate

# 2. Run backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

# 3. Run test suite
pytest -v
```

---

## API Endpoints

- `GET /health`: Health check for API, GraphHopper routing engine, and PostGIS.
- `POST /api/route`: Point-to-point routing with surface strip segmentation and miles/feet stats.
- `GET /api/edges/{osm_id}`: Query OSM edge heat and ride recency data.
- `POST /api/heat/record`: Ingest user ride edge heat into PostGIS.

### Example Route Request
```bash
curl -X POST http://localhost:8080/api/route \
  -H "Content-Type: application/json" \
  -d '{
    "start": {"lat": 43.1305, "lon": -71.3524},
    "end": {"lat": 43.1482, "lon": -71.3651},
    "profile": "mtb"
  }'
```