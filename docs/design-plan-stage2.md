# Loam Frontend Design Plan (Stage 2: MVP Routing & Map UI)

Written per Section 18 of `docs/trail-route-builder-plan.md` and `docs/agent-build-brief.md`.

---

## 1. Core Principles & Philosophy
- **Map First**: Full-bleed interactive map (`MapLibre GL JS`) covers 100% of the viewport. Controls live in an overlay panel (desktop) or adaptive bottom sheet (mobile).
- **Phone First**: Designed for outdoor trailhead conditions: 48px+ touch targets, high contrast under direct sunlight, operable with one thumb or light cycling gloves.
- **Show Why**: Every score, DNR warning, and trail confidence level is explained in plain words (e.g., *"12.1 mi vs 12.0 mi target; 58% singletrack vs 60% desired"*).
- **Signature Element — The Surface Strip**: A segmented horizontal bar directly beneath the elevation profile representing trail surfaces along the route (Singletrack, Doubletrack, Gravel, Paved).

---

## 2. Design Tokens & Styling Guide

### Palette (Field-Guide & Topographic)
- **Base Light (Fog)**: `#E7ECEC`
- **Text & Dark Base (Spruce)**: `#1D3B34` (passes WCAG AAA against Fog)
- **Primary Accent (Blaze)**: `#FF5B14` (used for selected route polylines and active indicators)
- **High-Contrast Action (Blaze Dark)**: `#C73E00` (used for primary action buttons with white text to achieve ≥4.5:1 contrast)
- **Secondary Accent (Slate)**: `#3F6C8F` (unselected alternative routes, water, secondary info)
- **Recency Fill (Lichen)**: `#A9BF7A` (used for fills and badges indicating recent heat or new trail discovery)

### Surface Color Mapping
- **Singletrack**: `#2E6F40` (Forest Green, thin solid line)
- **Doubletrack**: `#8D6E63` (Earthy Brown, medium solid line)
- **Gravel**: `#D4A373` (Light Buff, dashed line)
- **Paved**: `#78909C` (Muted Grey, thin solid line)

### Typography
- **Font Family**: Atkinson Hyperlegible
- **Numerals**: Tabular numerals enabled (`font-variant-numeric: tabular-nums`) for distances, climbing, and grades.
- **Scale**:
  - `Display / Miles`: 28px / 32px (Bold)
  - `Heading`: 20px / 24px (Semi-Bold)
  - `Body / Labels`: 16px / 20px (Regular)
  - `Meta / Captions`: 14px / 18px (Regular)
- **Case**: Strict sentence case throughout UI (no uppercase transforms).

### Shapes & Controls
- **Border Radius**: Consistent single radius (`8px` on buttons, inputs, chips).
- **Separation**: Clear dividers (`1px solid #D1D8D8`) and whitespace rather than nested cards with heavy drop shadows.

---

## 3. Screen Layout & Wireframes

### Mobile Adaptive Layout
```
+------------------------------------------+
|  [Search / Location]      [Layers] [GPS] |
|                                          |
|                FULL-BLEED                |
|                   MAP                    |
|                                          |
|==========================================|
| === Drag Handle ===                      |
| [Bike (MTB)]  [Run]       Target: 12.0 mi|
| Terrain: [===ST===|==DT==|==GR==|==RD==] |
| [ Build Routes ]                         |
|------------------------------------------|
| [ Plan ]    [ Explore ]  [ Saved ] [ You]|
+------------------------------------------+
```
- **Bottom Sheet Snap Points**:
  - *Peek (80px)*: Quick status / active route summary + Build action.
  - *Half (45% height)*: Input controls or results list.
  - *Full (90% height)*: Detailed route breakdown, turn sheet, or profile inspection.

### Desktop Layout
- **Left Panel (400px wide)**: Fixed sidebar for sport selection, waypoint list, terrain sliders, and result cards.
- **Main Viewport**: MapLibre canvas with hover-highlighting for route options.

---

## 4. Key Screens

### Screen A: Plan
1. **Sport Mode**: Toggle chips (`MTB`, `Gravel`, `Trail Run`).
2. **Waypoints**: Start, End, optional Detours. Support for **Round Trip / Loop** toggle.
3. **Distance Target**: Numeric stepper / slider in **miles** (never km).
4. **Terrain Mix Strip**: 4-way draggable segmented slider (Singletrack / Doubletrack / Gravel / Paved) with quick presets (*"Mostly Trail"*, *"Gravel Grind"*, *"Mixed Exploration"*).
5. **Mode**: Normal vs. *Find New Trails* (with novelty slider).

### Screen B: Results (Candidate Options)
- Streamed result cards (~10 options) ranked by match score.
- Each card displays:
  - Match Score (e.g., `94`)
  - Distance (e.g., `12.4 mi`) and Climbing (e.g., `1,420 ft`)
  - Compact Surface Strip showing terrain composition along the length
  - Mini-map / spatial footprint

### Screen C: Route Detail & Export
- Large Elevation Profile linked directly to the interactive Surface Strip.
- Hover/touch scrubbing along the profile highlights the exact position on the map and displays the surface type and grade.
- Verbal Score Explanation: *"12.4 mi vs 12.0 mi target (+3%); 62% singletrack (exceeds 60% goal); 0 closures or DNR conflicts."*
- Primary Actions:
  - **Download GPX / FIT**
  - **Share to Garmin Connect** (mobile share sheet)
  - **Save to Profile**

---

## 5. Technical Budgets & Stack
- **Framework**: React + TypeScript + Vite.
- **Map Library**: MapLibre GL JS + PMTiles / public vector tile provider.
- **Bundle Target**: < 250 KB JS initial bundle (excluding map gl engine).
- **Interaction Target**: Sub-100ms response on UI interactions; streaming candidate results as they resolve.
