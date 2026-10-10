# OpenTrailMap (OTM) & OpenStreetMap Architecture Investigation

**Date**: October 2026  
**Status**: Adopted Architecture (Replacing Trailforks)  
**Author**: Loam Engineering  

---

## 1. Executive Summary & Strategic Decision

During initial planning, Loam considered integrating the **Trailforks API** (Outside Interactive, Inc.) for trail condition reports, difficulty ratings, and official naming. However, evaluating Trailforks revealed significant obstacles:
- **Commercial Licensing Costs**: Trailforks imposes high enterprise licensing fees for external application developers.
- **Closed, Proprietary Lock-In**: Trailforks prohibits redistributing or caching trail GIS geometry, making self-hosted offline routing impossible.
- **External Dependency Risk**: Reliance on a closed third-party API conflicts with Loam's design goal of operating autonomously on a local Raspberry Pi node.

**Strategic Decision**: Loam will **not** use Trailforks. Instead, Loam will build entirely upon **OpenStreetMap (OSM)** and the **OpenTrailMap (OTM)** initiative. This delivers:
1. **Zero Recurring API Costs**: Complete financial independence with no paywalled data.
2. **True Local Deployment**: All routing graphs and trail geometry run locally in GraphHopper and PostGIS on the Raspberry Pi node.
3. **Open Standards Alignment**: Compatibility with OpenStreetMap US trail tagging guidelines.
4. **Community Stewardship**: Loam's community check-in and flag layers complement open data rather than enriching a closed corporate database.

---

## 2. What is OpenTrailMap (OTM)?

**OpenTrailMap** is an initiative led by **OpenStreetMap US** ([trails.openstreetmap.us](https://trails.openstreetmap.us/)) in conjunction with the Trails Working Group, federal land management agencies (USFS, NPS, BLM), and regional trail advocacy organizations (e.g., NEMBA).

Unlike proprietary platforms that silo user contributions behind paywalls, OpenTrailMap establishes open specifications and validation pipelines directly on top of OpenStreetMap.

### Standardized Tagging Schema

| Tag | Purpose | Example Values | Loam Application |
|---|---|---|---|
| `highway=path` | Core trail way indicator | `path`, `footway`, `track` | GraphHopper routing edge |
| `name=*` | Official trail name | `Boundary`, `Boulder`, `Podunk` | Primary UI label and turn directions |
| `mtb:scale=*` | MTB difficulty (Singletrail Scale 0–6) | `0` (green), `1` (blue), `2` (black) | Skill level matching and filtering |
| `sac_scale=*` | Hiking / trail run difficulty | `hiking`, `mountain_hiking`, `demanding_mountain_hiking` | Trail running technicality scoring |
| `surface=*` | Ground surface composition | `dirt`, `ground`, `gravel`, `rock` | Surface breakdown bar in route cards |
| `operator=*` | Managing land agency or club | `NH State Parks`, `NEMBA` | Land manager awareness and DNR tagging |
| `trail_visibility=*` | Trail tread clarity | `excellent`, `good`, `intermediate` | Navigation confidence scoring |
| `informal=yes` | Social / rogue trails | `yes`, `no` | DNR / soft warning exclusion |

---

## 3. Loam Technical Integration Architecture

```
                                      +-------------------------------+
                                      |   OpenStreetMap Planet / PBF  |
                                      |   (Geofabrik NH / New England)|
                                      +---------------+---------------+
                                                      |
                                                      v
                                        [ GraphHopper Engine ]
                                        - Custom profiles (MTB, Foot)
                                        - Surface & mtb:scale weights
                                                      |
                                                      v
+-------------------------------+      +--------------+----------------+
|    Loam PostgreSQL / PostGIS  | <--- |   Loam Edge Ingestion Pipe   |
|   - Real trail names registry |      |   - OSM Way ID association    |
|   - Heat index & ride history |      |   - Geometry & bbox indexing  |
|   - Community Trust Layer     |      +-------------------------------+
+---------------+---------------+
                |
                v
+-------------------------------+
|      Loam Client UI (Web)     |
|   - Blaze route lines         |
|   - Real named trails         |
|   - Heatmap layer overlay     |
|   - Lollipop loop support     |
+-------------------------------+
```

### 3.1 Real Trail Name Resolution Pipeline
To ensure riders see authentic trail names (such as **"Bear Brook — Boulder Trail Loop"** or **"Boundary Trail"**) rather than synthetic edge IDs (e.g., `Trail #42743791`):

1. **Local Graph Details**: GraphHopper routes are configured to extract the `street_name` detail from the underlying OSM PBF tag.
2. **Curated Known Trails Registry**: `app/db.py` maintains an indexed catalog of prominent New England trail networks (`KNOWN_OSM_TRAIL_NAMES`).
3. **Database Edge Resolution**: When way IDs are identified along a route, Loam resolves `edges.name` from PostgreSQL.
4. **Online OSM Way Lookup**: If a way has not yet been indexed locally, Loam queries the OpenStreetMap API (`/api/0.6/way/{id}.json`) to retrieve official community-maintained names.

### 3.2 Community Trust Layer vs. Proprietary Reports
Trailforks relies on centralized status updates. Loam implements an open **Community Trust Layer**:
- **Check-ins**: Riders submit real-time confirmations ("Still open", "Blowdown cleared") directly from the route view.
- **Condition Flags**: Warnings for seasonal mud closures, high water crossings, or blowdowns.
- **Upstream Feedback**: Flagged errors in trail routing can be submitted to OSM mapping workflows.

---

## 4. Platform Comparison Matrix

| Feature | Trailforks (Outside Inc.) | OpenTrailMap / OSM (Loam) |
|---|---|---|
| **License & Access** | Proprietary, commercial, closed | ODbL / Open Data, 100% Free |
| **API Costs** | High enterprise subscription tiers | $0 / Free forever |
| **Offline Raspberry Pi Hosting** | Impossible (requires outside cloud) | Native (runs fully on `core-node.local`) |
| **Geometry & GeoJSON** | Restricted, prohibited from export | Native GeoJSON export, GPX, FIT |
| **Trail Naming** | Trailforks admin approval required | Community-driven OpenStreetMap registry |
| **Heatmap Visualization** | Paid feature behind Pro paywall | Built-in Loam heatmap layer (`GET /api/heat/trails`) |
| **Route Customization** | Generic trail links | Multi-quadrant loops, lollipop loops, surface biasing |

---

## 5. Implementation Roadmap

### Phase 1: Completed in Round 3 Fixes
- Implemented real OSM trail name resolution in `app/db.py` and `app/routing.py`.
- Replaced synthetic `Trail #...` text in `ExplorePanel.tsx` and route titles.
- Added GeoJSON heat trails endpoint (`/api/heat/trails`) and client MapLibre heatmap layer with toggle.
- Added strict loop filtering and lollipop loop geometry classification (`classify_route_geometry`).

### Phase 2: Automated Regional PBF Ingestion
- Nightly Overpass / Osmosis synchronization for northern New England trail ways.
- Direct tagging of `mtb:scale` and `sac_scale` into `edges.metadata` JSONB.

### Phase 3: Upstream OSM Contributions
- Enable authenticated Loam users to export verified trail submissions as OSM Changeset XML for review in JOSM or iD editor.
