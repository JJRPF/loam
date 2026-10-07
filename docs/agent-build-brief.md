# Agent Build Brief: Trail Route Builder (working name: Loam)

Read `trail-route-builder-plan.md` first. This brief says how to build it.

## Environment

- Dev machine: MacBook (Omarchy). You work on the Raspberry Pi 5 over SSH.
- Repo: public GitHub, open source. Pick a license only after Justin chooses.
- Pi: NVMe preferred, 8-16 GB RAM. Build the first routing graph on the MacBook and copy it to the Pi; measure re-import on the Pi for nightly heat updates.
- Network: UniFi router, port 443 forwarded to the Pi, Caddy for HTTPS, dynamic-DNS updater for Google Cloud DNS.
- Frontend: static PWA on Firebase Hosting, Firebase Auth (Google sign-in). The Pi API verifies Google ID tokens.
- Everything must stay within free tiers. Show miles in the UI, never kilometers.

## Guardrails (read first)

- Do not change router, firewall, port-forward, or DNS settings, and do not expose any new port. Ask Justin and wait.
- Work in git on a branch. No secrets, keys, tokens, or personal GPS data in the repo; keep them in env files outside version control and enable secret scanning.
- Use separate dev and production databases. Back up before any schema migration or bulk data change.
- No destructive commands (dropping databases, wiping disks, deleting outside the project) without approval.
- Do not enable the Trailforks, Strava, or Garmin-login connectors until Justin has read the current terms and confirmed here.
- Cloud credentials: least privilege, stored outside the repo.

## Stack

- Backend: Python, FastAPI
- Routing: GraphHopper with custom models
- Database: PostGIS
- Frontend: TypeScript PWA with MapLibre
- Tiles: free public vector tile provider first (read its terms; never use tile.openstreetmap.org); self-hosted PMTiles later
- Elevation: USGS 3DEP preferred; SRTM is too coarse for trail-scale climbing
- Jobs: simple worker and queue on the Pi

## Frontend and UX

Follow section 18 of the plan (principles, palette, type, layout, flows, states, accessibility, budgets). Before stage 2, write a one-page design plan and check it against that section. Phone first, map first, and the surface strip is the signature element.

## Work in this order. Do not start a stage until the previous one passes its check.

1. **Foundation and spikes:** OSM extract (NH), PostGIS, GraphHopper, basic API. Spikes with written conclusions: (a) how nightly heat gets into the router (GraphHopper cannot query PostGIS per request; compare re-import with heat as an encoded value, rank-only heat, and another engine), (b) elevation source, (c) latency of generating about 10 options on the Pi. Check: a point-to-point route returns in a few seconds and the spikes are written up. Stop and report the heat-in-router result to Justin before stage 2.
2. **MVP routing:** map UI built to section 18, inputs (start, end, midpoints, loop, round trip, distance), terrain sliders and presets, MTB profiles and trail-run profile, GPX and FIT export, Google sign-in, saved routes. Check: a New Hampshire route downloads and opens on a Garmin fenix 7 Pro.
3. **Options and scoring:** generate about 10 distinct routes with miles, climbing, minimap, and match score. Score = 60% input match, 15% heat, 10% mode value, 10% quality, 5% penalties. Check: ten valid, distinct options.
4. **Heat v1:** GPX/FIT uploads, map-matching, nightly job, 12-month window with about 6-month half-life, OSM public-trace seed, Justin's own ride archive as first data. Check: Justin supplies 5-10 known ghost trails and 5-10 known good trails in an area he knows well; ghost trails are avoided and good ones used.
5. **Trust layer:** flags, "still open" check-ins, DNR list, closures, consent and opt-out. Check: privacy tests pass.
6. **Differentiators:** Find New Trails mode, trail submissions, trail running polish, optional Strava connector, optional Garmin login connector (feature-flagged).

Then: **testing**, then a second **upgrade round** from what testing finds.

## Rules that must never break

- **Privacy:** heat needs explicit user consent. Opt-out any time. Trim ride starts and ends (first and last 0.2 mi). A trail's heat is shown to others, and influences their routes, only where at least 3 unique riders contributed; below that it counts only for the contributor. Support privacy zones, delete raw uploads after map-matching unless the user keeps them, and provide account deletion and data export. Never expose an individual's ride to others.
- **DNR:** user-settable. Soft DNR warns and allows override (log it). Hard blocks (closures, sensitive land, wildlife) cannot be overridden. A DNR is waived only if the user already rode that trail.
- **Zero-heat trails:** avoid by default, user can override, overrides weakly reduce the penalty for others. Apply the penalty only where local data coverage is good; elsewhere heat is neutral and the UI says "No recent data".
- **Access:** hard-block OSM `access=private/no`, `bicycle=no`, wilderness and other bike-prohibited protected land. Snowmobile trails are permission-based and seasonal: warn, never present as public access.
- **Trail submissions:** auto-verify only when at least 3 unique riders overlap the geometry in 12 months and no restricted area is hit. Otherwise stay hidden until crowd-confirmed using GPS-backed evidence, account-age weighting, and rate limits (accounts are cheap, so votes alone are not trusted). No routine moderation, but the admin can reverse any decision and act on takedown requests.
- **Attribution:** show "© OpenStreetMap contributors". Credit Trailforks wherever its data appears.
- **Trailforks:** build the interface only. Do not ingest any Trailforks data until Justin confirms permission. Free product only, respect rate limits, never feed its data into OSM.
- **Connectors:** Strava, Garmin login, and Trailforks sit behind interfaces so any can be switched off without breaking the app.
- **Garmin login:** never store passwords. Exchange for session tokens, encrypt them, never log credentials. MVP does not need it.
- **Security:** no secrets in the repo, firewall and fail2ban on the Pi, rate limiting (Caddy needs a custom build for it, or do it in the app), SSH not exposed to the internet, encrypted disk and backups, defensive parsing of uploaded GPX/FIT (size limits, safe XML).
- **Cost:** no paid services. No paid tier or ads; donations only.

## Testing

- Automated: route validity (no routes through hard blocks), graph checks, scoring tests, privacy-threshold tests, token verification tests.
- Ghost-trail test set from Justin, run after every heat change.
- Manual: Justin and friends ride or run generated routes, then log ghost trails, wrong terrain, and bad scores as issues.

## Report back

After each stage, summarize what passed, what failed, and any decision you need from Justin.