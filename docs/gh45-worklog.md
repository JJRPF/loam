# GH-45 worklog: staging + production auto-deploy

Plan: the first comment of issue #45. Reference: justinpfister/portal PR #25.

## Phase 0: Inventory

Read-only look at production. I could not log in to the Pi from this session (the SSH read was blocked by the
environment's permission check), so only the public side was read:

- `https://core-node.tailcd5892.ts.net/health`: `status ok`, GraphHopper and PostGIS up, `usgs_3dep (12 DEM tiles)`.
- `/api/config`: `midpoints_enabled false`, `min_unique_riders 3`, `seed_heat_public true`, connectors garmin and cubetrek on.
- What never shipped: the last deploy (Phase 10 of `docs/round8-worklog.md`, 2026-10-14) was the GH-38 branch, which
  merged as `6f55210`. The only commit on `main` since is `57957fe` (README text). So nothing of substance is waiting;
  the first auto-deploy of this PR's merge will ship the deploy tooling and the GH-45 changes only. To be confirmed on
  the Pi by the owner (`~/loam` has no git history: compare a file hash, or read `REVISION` once the first release lands).
- The Pi serves `frontend/dist` on the LAN through the API's static mount. The new release has no `dist` (it is built
  in CI and deployed to Firebase Hosting), so after the first auto-deploy the Pi serves the API only. See DEPLOYMENT.md.

Nothing was deployed.
