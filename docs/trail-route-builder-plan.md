# Trail Route Builder: Project Plan

Working name: **Loam** (alternates: Ridden, Rideable). Name is a placeholder until the agent's SEO/domain tests finish. Ridden and Rideable lean bike-only; Loam works for biking and running.

## 1. Vision

A route builder for mountain biking and trail running that does what TrailRouter, Strava's builder and bike-router.de do, plus:

- Terrain-mix control (road, gravel, doubletrack, singletrack, snowmobile trail, rail trail)
- A **recency heat layer** that prefers trails ridden or run in the last 12 months, so routes avoid trails that no longer exist
- A **Find New Trails** mode
- About 10 ranked route options per request, each with miles, climbing, minimap and match score
- One-tap export to Garmin and GPX/FIT

Success: a tool Justin uses weekly, plus some real users (friends, family, local riders).

## 2. Locked decisions

- Platform: PWA (web + phone), wrapped later with Capacitor if needed
- Region: New Hampshire first, then New England; other regions on request
- Sports: mountain bike (hardtail, full-sus, gravel, fat, e-MTB) and trail running
- Auth: Google SSO (Firebase Auth)
- Heat data: user uploads and connections (Strava included, as a swappable module), OSM public traces, OSM freshness tags, rider check-ins
- Zero-trail-heat: avoid, user can override; overrides feed back as a weaker penalty for others
- Restrictions: user-settable do-not-route (DNR) honored unless the user already rode that trail or overrides; hard blocks for closures and sensitive land
- Ranking: combined score, input match first
- MVP export: GPX/FIT download plus phone share sheet into Garmin Connect (no Garmin credentials needed). Official Garmin API: not used. Optional direct push later via the user's own Garmin login (see section 13)
- Monetization: none. Free product, donations only (see section 12)
- Units: miles in the UI
- Frontend: static PWA on Firebase Hosting with Firebase Auth; the Pi verifies Google ID tokens itself
- API hosting: Pi behind a regular port forward (UniFi router), Caddy for HTTPS, at an `api.` subdomain. The home IP is public in DNS; this is accepted and mitigated in section 3
- Code: open source on GitHub (license to be chosen)
- Dev setup: MacBook running Omarchy; the agent works on the Pi over SSH
- Trail submissions: auto-verify or crowd-confirm only, no manual moderation

## 3. Architecture

```
Phone/Web PWA --> domain (Google Cloud DNS) --> home router (port 443 forward) --> Caddy (HTTPS) --> Pi 5
                                                   |- API (FastAPI)
                                                   |- GraphHopper (routing)
                                                   |- PostGIS (edges, heat, flags, users)
                                                   |- Worker (heat pipeline, route generation queue)
                                                   '- PMTiles (optional self-hosted tiles, later)
Firebase Auth + Hosting (free) --> login + static PWA (calls api.<domain> on the Pi)
```

Hardware guidance:

- Use an NVMe SSD, not the SD card. Target 16GB RAM, 8GB workable.
- Build the first routing graph on the MacBook and copy it to the Pi. Nightly heat updates may force re-imports on the Pi (see section 5), so measure import time and RAM there.
- Free Google Cloud egress is about 1 GB/month, so do not serve tiles or downloads from GCP.
- Keep a budget alert on the GCP project.
- **Exposing the Pi (no Cloudflare Tunnel):** forward port 443 on the UniFi router to the Pi. Caddy gets its HTTPS certificate automatically over 443, so no DNS-challenge plugin is needed. Rate limiting needs a third-party Caddy module (custom build with xcaddy), so decide early whether to use that or limit in the app. A small script updates the `api.` A record in Cloud DNS when the home IP changes. Give it a dedicated service account with the narrowest role possible; Cloud DNS roles are coarse, so a leaked key could edit other records in that project (which another project pays for). Put the Pi on its own UniFi network or VLAN, enable the firewall and fail2ban, and keep SSH off the public internet. Confirm Fidium allows inbound 443.
- **Tiles:** start with a free public vector tile provider (the agent must read its usage terms; never use tile.openstreetmap.org, whose policy forbids heavy use). Self-hosted PMTiles are a later option. Route responses and GPX downloads come from the Pi; keep them small and compressed.
- **Elevation:** pick a DEM source early. SRTM is too coarse for trail-scale climbing numbers; prefer USGS 3DEP (10 m or better) and verify it loads into GraphHopper.
- **User data on the Pi:** it stores GPS history, so encrypt the disk and backups, parse uploaded GPX/FIT defensively (size limits, safe XML parsing), and use least-privilege service accounts.
- Pi backup: nightly PostGIS dump to a free cloud bucket or the e2-micro.

## 4. Data layer

**Base map:** OSM extract (Geofabrik) for New Hampshire, then New England. Attribute: ODbL, show "© OpenStreetMap contributors."

**Edge attributes (per way segment):** surface, tracktype, `mtb:scale`, `mtb:scale:uphill`, bicycle/foot access, highway type, snowmobile flag, sac_scale (running), grade, length, last OSM edit date, `check_date`.

**Core tables:**

- `edges` (osm id, geometry, attributes)
- `edge_heat` (edge, sport, unique riders 12 mo, weighted score, last ridden date)
- `flags` (edge, type: gone/blocked/closed/seasonal, user, date, confirmed count)
- `restrictions` (edge or area, type: DNR/closure/sensitive, source, hard/soft)
- `users`, `saved_routes`, `contribution_consent`
- `trail_submissions` (geometry, status, verifier count)

## 5. Routing engine

- **GraphHopper** with per-request custom models. Each terrain slider and sport profile becomes weight multipliers.
- **Profiles:** mtb-hardtail, mtb-fullsus, gravel, fat (winter, snowmobile trails boosted), emtb (blocks no-e-bike trails), trail-run (allows foot-only trails and stairs, higher grade tolerance).
- Terrain mix: user targets (for example 60% singletrack / 30% gravel / 10% road) with presets they can adjust. Treated as a soft target in scoring, not a hard constraint.
- "Stay on trail" toggle: heavy penalty on paved road, off by default.
- Midpoints, round trip, loop, out-and-back all supported.
- **Known technical risk: heat inside the router.** GraphHopper custom models use per-edge values baked in at graph import; they cannot query PostGIS per request. Nightly heat therefore needs one of: (a) a nightly re-import with heat as an encoded value (test import time and RAM on the Pi), (b) heat applied only when scoring and ranking candidates, which cannot steer the search away from ghost trails, or (c) a different engine (for example pgRouting). Settle this in a stage 1 spike before building on top. Per-request custom areas (GeoJSON polygons) fit DNR and closures well.

## 6. Generating \~10 options

1. Pick the target miles and shape (loop, point-to-point, via midpoints).
2. Generate 40-60 candidates with varied seeds, headings, and detour waypoints.
3. Reject candidates that violate hard blocks or fall outside distance tolerance (+/-10%).
4. Score each candidate (below).
5. Remove near-duplicates (more than 70% shared edges), then return the top 10.
6. Return per option: miles, climbing, descending, terrain split, minimap, match score, DNR warnings.

Queue generation, cache by input hash, and cap concurrent jobs to protect the Pi. Measure the candidate count against Pi latency, and reduce it if the first result takes more than about 10 seconds.

**Score (0-100):**

- 60%: input match (distance, terrain mix, elevation target, shape, midpoints)
- 15%: heat (recent usage, weighted toward the last 6 months)
- 10%: mode value (Find New Trails raises "new to me"; Normal raises "popular")
- 10%: quality (difficulty fit, surface, continuity, fewer road crossings)
- 5%: penalties (open flags, seasonal issues, DNR overrides)

## 7. Heat pipeline

**Sources:**

1. User GPX/FIT uploads (primary)
2. Strava connector (user's own activities) and Strava data-archive upload. Isolated behind an interface so it can be turned off.
3. Garmin Connect via optional user login (unofficial, feature-flagged); Komoot later if a route is available 3b. Trailforks (registered API user): trail names, difficulty, status and condition info as a trail-existence signal. Free product only, credit Trailforks, respect rate limits and regional download restrictions, and do not feed Trailforks data into OSM. Check exactly what the API exposes and ask Trailforks for permission before relying on it.
4. OSM public GPS traces: mostly old, so use them only to find candidate trails, never as recency heat
5. OSM freshness proxies (edit date, `check_date`)
6. Rider check-ins ("still open" one-tap)

**Processing:** nightly job: map-match activities to edges, count unique riders per edge per sport, apply a recency decay (about 6-month half-life, 12-month window), update `edge_heat`.

**Coverage-aware penalty:** no data does not mean a dead trail. Apply the "no recent heat" penalty only in areas with enough contributing rides (set a regional threshold). Elsewhere treat heat as neutral and show "No recent data". Otherwise a cold start would prune most of the state and route only along Justin's own rides.

**Privacy rules:**

- Consent required to contribute; opt-out at any time, per ride or entirely.
- Trim ride starts and ends (first and last 0.2 mi).
- A trail's heat is shown to others, and influences their routes, only where at least 3 unique riders contributed. Below that it counts only for the contributor's own routes. Otherwise one person's ride on a private or unsanctioned trail would route strangers onto it.
- Privacy zones: users can hide a radius around home or work, in addition to the start and end trim.
- Retention: delete raw uploaded files after map-matching unless the user chooses to keep them. Keep derived per-edge visits only. Provide account deletion and data export.
- Never show or export individual rides to other users.

## 8. Restrictions and closures

- **DNR list:** user-settable by area and trail. Soft DNR: warn, allow override, log it. Hard blocks (closures, wildlife, private land): no override.
- **Closure sources:** land manager and trail association feeds where available, plus rider flags.
- Seasonal tags: mud season, hunting season, winter closures.
- **Access data (hard-block defaults):** ingest OSM `access=private/no` and `bicycle=no`, plus protected-land boundaries (for example USGS PAD-US) and treat wilderness and other bike-prohibited areas as hard blocks. Verify New Hampshire's specific rules.
- **Snowmobile trails:** many may cross private land by landowner permission and may be seasonal. Tag them as permission-based, warn in the UI, and never present them as public access.
- **Admin override:** Justin can add, edit, and remove restrictions and takedowns directly. There is no routine moderation, but a land manager's takedown request must be actionable quickly.

## 9. Find New Trails mode

- Shows trails with strong recent heat that the user has not ridden or run.
- Builds routes that include a set minimum of new miles (user slider).
- "Unridden" tracked from the user's own history.
- Also surfaces trails missing from OSM that heat shows are real (feeds section 10).

## 10. Trail submissions and verification

- Users trace or upload a trail with a name, sport, and difficulty.
- **Auto-verify** when at least 3 unique riders' rides overlap the geometry in the last 12 months and it doesn't hit a restricted area.
- Otherwise: pending and hidden until confirmed by distinct riders (votes or check-ins). No routine moderation.
- **Abuse resistance:** Google accounts are cheap, so three accounts could fake a trail or a closure. Require GPS-backed evidence (an overlapping ride), not just votes; weight confirmations by account age and history; rate-limit flags and submissions; and let the admin reverse any decision.
- Option to export confirmed trails as an OSM edit (via the user's own OSM account), later phase.
- Land-use check against known restricted areas before publishing.

## 11. Features

UX and frontend design guidance is in section 18. **MVP:** route builder (start, end, midpoints, loop, round trip), distance/terrain/elevation inputs, 10 options with score and minimap, Garmin share/GPX/FIT export, Google sign-in, saved routes.

**Later:** heat map layer, flags and check-ins, DNR, Find New Trails, elevation profile with surface overlay, weather/conditions, water/bike shop/bailout markers, offline maps and turn-by-turn, shared route links, friends, seasonal (fat bike, mud) modes, trail running profile polish, contributor perks.

**Contributor perks:** full heat layer and "new trails near me" for contributors, personal "network ridden %" map, extra daily route generations, first-to-confirm badges, local leaderboards. All opt-in.

## 12. Funding and access

- Free product. No paid tier, no ads.
- Donation link (and optionally a sponsor thank-you page) to cover domain and hardware.
- Previously "Pro" features (offline maps, unlimited saves, winter modes, direct Garmin push if stable) become **contributor perks**: unlocked by contributing rides, confirming trails, or submitting trails, or granted manually by the admin.
- Keeping the product free is what makes Trailforks data usable (its terms require free access). Re-check the donation wording against Trailforks terms, and credit Trailforks wherever its data appears.

## 13. Legal and risk (no lawyer)

- Use reputable plain-language templates for terms of service and privacy policy, with explicit consent text for heat contributions.
- Include a safety/liability disclaimer: user is responsible for access rules and conditions.
- Strava risks: API terms limit showing one user's data to others and ban AI/ML use; Strava also holds a patent (US 9,778,053) on routing from aggregated activity heat. Keep the project small and private until you've reviewed this. Keep the connector swappable.
- Keep the public launch gated (invite list) until terms are solid.
- A public GitHub repo makes the heat-based routing approach visible, and the patent concern applies whether or not the code is open source. Keep the user base small until you've decided how to handle it.
- The Strava connector ships off by default. The agent must read the current Strava API agreement first (it changed in 2026 and may require approval). Do not ingest any Trailforks data until Justin confirms permission.
- **Garmin login (unofficial):** no official Garmin API. MVP needs no Garmin credentials (GPX/FIT download and share sheet). If you add "Connect Garmin" by login: the user enters credentials once, the app exchanges them for session tokens and discards the password, tokens are encrypted at rest, credentials are never logged, MFA is handled, and the feature sits behind a flag. Expect it to break whenever Garmin changes login, and it may violate Garmin's terms. Start with your own account only before offering it to others.

## 14. Build process (agent-driven, no fixed calendar)

The agent works through the stages in order until the app works, then testing, then a second round of upgrades. Each stage must pass its acceptance check before the next starts.

**Round 1: build to working**

1. **Foundation and spikes:** OSM extract, PostGIS, GraphHopper on the Pi, basic API, plus three spikes: how heat gets into the router (section 5), the elevation source, and 10-option latency on the Pi. Check: a point-to-point route returns in a few seconds, and each spike has a written conclusion.
2. **MVP routing:** map UI, inputs, terrain sliders, loop and midpoint routing, GPX/FIT export, Google sign-in, saved routes. Check: a New Hampshire route downloads and opens on the fenix.
3. **Options and scoring:** 10-option generation, scoring, minimaps. Check: ten distinct, valid options with sensible scores.
4. **Heat v1:** uploads, map-matching, nightly job, recency weighting, OSM seed, plus Justin's own ride archive as the first real heat data. Check: Justin supplies 5-10 known ghost trails and 5-10 known good trails in an area he knows well; ghost trails are avoided and good ones are used.
5. **Trust layer:** flags, check-ins, DNR, closures, consent and privacy tools. Check: privacy threshold and opt-out tests pass.
6. **Differentiators:** Find New Trails, trail submissions, trail running profile, optional Strava and Garmin connectors.

**Milestone: working app.** Sign in, build a route, get 10 scored options, export to Garmin.

**Testing:** the agent's automated tests (route validity, graph checks, privacy thresholds) plus real rides and runs by Justin and friends and family. Log wrong routes, ghost trails, and scoring misses.

**Round 2: upgrades:** fixes and tuning from testing, deferred features (offline maps, weather, friends, contributor perks, more regions).

Goal: be in testing by early spring 2027 so riding season is covered.

## 15. Risks

- Heat is thin at first (cold start). Mitigate with the OSM seed, personal rides, and local beta riders.
- Pi load. Mitigate with a queue, caching, and NVMe.
- Home internet or Pi outages. Mitigate with nightly backups, a dynamic-DNS updater, a status page, and a UPS if affordable.
- Strava policy or patent action. Mitigate with a modular connector and consent-based uploads.
- Pi exposed to the internet and home IP visible. Mitigate with Caddy rate limiting, firewall, fail2ban, a separate network segment, automatic updates, and no open ports besides 443.
- Sensitive trail exposure. Mitigate with hard blocks, a 3-rider display threshold, and a takedown channel.
- Fake or malicious flags and trail submissions (section 10).
- Heat-in-router method unproven (section 5 spike).
- Solo time budget. Keep each phase shippable.

## 16. Costs

Near zero ongoing: the Pi (plus NVMe and, if needed, a UPS), domain (about $10-20/year), and a free-tier budget alert. Donations cover what they can. Revisit if traffic grows past free limits.

## 17. Open items

- Final name and domain after SEO tests
- Terms of service and privacy templates chosen
- NVMe upgrade for the Pi
- First beta list (friends, family, local clubs)
- Choose the open-source license (check compatibility with OSM's ODbL and Trailforks' terms)
- Test inbound 443 through the UniFi router and the dynamic-DNS updater
- Ghost-trail and good-trail test set from Justin
- Read the current Strava and Trailforks terms before enabling either

## 18. UX and frontend design

### Principles

- **Map first.** The map fills the screen; everything else is a panel over it.
- **Phone first.** People use this at trailheads: one thumb, gloves, sun glare, weak signal.
- **Show why.** Every route score and trail status explains itself in plain words.
- **One signature element: the surface strip.** A horizontal band showing a route's terrain along its length (singletrack, doubletrack, gravel, road), shown under the elevation profile. It appears on every result card and on route detail. Everything else stays quiet.

### Visual direction

Topographic and field-guide, not a fitness-app look. Avoid cream-and-terracotta and black-and-neon defaults, gradient washes, identical rounded cards with matching shadows, all-caps labels, and decorative numbering.

Palette:

- Fog `#E7ECEC`: light base
- Spruce `#1D3B34`: text, headers, dark-mode base
- Lichen `#A9BF7A`: recently used trails, "new" highlights
- Slate `#3F6C8F`: water, info, secondary route options
- Blaze `#FF5B14`: the selected route and the single primary action on each screen

The heat layer uses its own hue ramp (teal to pale) so it never competes with route lines. Contrast warning: by my calculation, white text on Blaze is only about 3:1, and Lichen on Fog is too light for text. Use Blaze for lines and large elements, use a darker orange (about `#C73E00`) for buttons with white text, and keep Lichen for fills. Verify every pairing reaches 4.5:1 in light and dark modes, and test on a phone in direct sun.

Type: one family, Atkinson Hyperlegible (free, built for legibility), with tabular numerals for miles and climbing. Sentence case. Scale: 14 / 16 / 20 / 28, with large numerals for miles.

Shape: one corner radius for controls. Separate content with spacing and dividers, not stacked shadow cards.

Map style: a custom MapLibre style with a muted base so routes and heat stand out. Add hillshade and contours. Draw trails by surface using line style as well as color (singletrack thin solid, doubletrack medium, gravel dashed, paved grey).

### Layout

```
Mobile                         Desktop
+------------------+           +--------+--------------------+
|   full-bleed map |           | panel  |                    |
|                  |           | (400px)|        map         |
|==== sheet =======|           |        |                    |
| peek/half/full   |           +--------+--------------------+
| Plan Explore Saved You |
+------------------+
```

Mobile: the bottom sheet has three snap heights (peek, half, full), with bottom tabs: Plan, Explore, Saved, You. Desktop: left panel plus map, with a hover preview of each result on the map.

### Core flows

**Plan**

1. Choose Bike or Run (changes terrain categories and estimated time).
2. Start, end, and midpoints: tap the map, search, or use current location. Options: Round trip, Loop, Out and back.
3. Distance in miles; optional climbing and time targets.
4. Terrain mix: one stacked bar with draggable dividers, plus preset chips and a "Mostly trail" toggle. Show at most four groups by default (for example Singletrack, Doubletrack, Gravel, Road) and expand to the rest, since six draggable segments are hard to use with a thumb.
5. Mode: Normal or Find new trails (slider for how many new miles).
6. Button: **Build routes**.

**Results:** show progress while building and stream cards in as they finish. About 10 cards, each with a minimap, miles, climbing, the surface strip, and a match score. Tap one for detail: route on the map, elevation profile with surface strip, score breakdown in words ("12.1 mi vs 12 target; 58% singletrack vs 60%"), and warnings (DNR, seasonal, flagged). Actions: **Download for Garmin** (GPX/FIT), **Share to Garmin Connect**, **Save**.

**Explore:** heat layer toggle with a legend ("Ridden in the last 12 months"), Find new trails highlights, and a trail sheet showing status ("Confirmed open 3 days ago"), **Still open** and **Report a problem** buttons, last ridden, and rider count (only when at least 3).

**Contribute:** a one-sentence explanation of what is shared, a per-ride privacy toggle, and perks shown as unlocks, never as guilt.

**Settings:** bike type, DNR list, contribution consent. Units are miles.

### Trust and edge states

- Thin data: dashed line with "No recent data" where coverage is thin; "Few recent rides here" only where coverage is good.
- Hard block: "Closed. Routes can't go here."
- Soft DNR: warning with **Route anyway**.
- Weak signal: "Waiting for connection"; saved routes and the last results work offline.
- Errors say what happened and what to do. Empty states invite action ("No rides yet. Upload a ride to see where you've been.").

### Copy

Plain verbs, sentence case, no filler. Keep action names consistent through a flow (Build routes, then "Routes built"). Say "Contributor perks", never "Pro" or "Premium".

### Accessibility and motion

Tap targets at least 48 px, visible keyboard focus, color never the only signal (line style and labels too), and reduced motion respected. Motion answers actions only: the route draws on when selected, and the sheet snaps between heights. No entrance animations.

### Frontend stack and budgets

Vite, React, TypeScript, MapLibre GL JS, CSS variables for design tokens. A service worker (Workbox) and IndexedDB keep saved routes and the last results available offline. Builder state lives in the URL, so every search is a shareable link. Budgets: first load under about 250 KB of JavaScript excluding the map library, interactions under 100 ms, first route result within about 10 seconds on the Pi (stream the rest).

### Design process for the agent

Before building, write a one-page design plan (tokens and wireframes for the Plan, Results, and Route detail screens) and check it against this section. Build the Plan screen first and test it on a real phone outdoors.