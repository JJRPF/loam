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

## Phase 1: Version info and the staging banner

- `app/deploy_info.py` + `GET /api/version` (sign-in required, via `get_current_user`): env, sha, short sha and whatever `deploy-info.json` holds (PR, title, URL, branch, commits ahead, deployed at). The file is re-read when its mtime changes; without it the answer falls back to `REVISION` / git.
- `app/config.py`: `staging_problems` / `check_staging_config`, run from `check_production_config` at import. Refuses: the production database name (`loam`), `GITHUB_FEEDBACK_TOKEN`, Strava or Trailforks enabled, the development `CONNECTOR_SECRET_KEY`, a production origin in `CORS_ORIGINS` or `PUBLIC_APP_ORIGIN`, the Auth emulator. Decision on the plan's "or point it at a test repo": refuse outright (simplest, and no token is needed on staging; the report button then leaves reports pending, as in development).
- "Connectors' live credentials": the app has no connector credentials of its own (Garmin/CubeTrek take the rider's login; Strava and Trailforks are flag-gated and off), so the guard is on those flags.
- `X-Robots-Tag: noindex, nofollow` on every staging API response, and a `/robots.txt` route that exists only in staging.
- `frontend/src/components/StagingBanner.tsx`: only when `VITE_APP_ENV=staging` and signed in; a 24 px strip (PR link, title, branch, commit link, commits ahead). It sets `--staging-banner-h` so the app shell moves down instead of being covered.
- Tests: `tests/test_gh45_deploy.py` (each guard, deploy-info, version needs auth, noindex).

## Phase 2: Pi side (written, not run on the Pi)

`scripts/deploy/pi/`: `loam-deploy-gate` (forced command: `deploy`, `stage`, `stage-main`, `status`; 40-hex sha, numeric pr, base64 meta up to 4096 characters), `loam-deploy-run` (lock, mirror check, `git archive` release, venv per requirements hash, backup then migrations, symlink switch, health check, rollback, keep 3), `loam-mirror-sync`, `write-deploy-info.py` (allow-listed meta keys, GitHub-only links), `loam-with-env` (reads `.env` like systemd, so a `$` in a secret is safe), `loam-deploy.sudoers`, `provision.sh` (check / install / switch-production), `refresh-staging-data.sh`, `loam-api-staging.service`.

Verified here: `tests/test_gh45_deploy_scripts.py` runs the gate with a fake sudo (valid commands, 29 malformed or hostile ones) and the runner end to end against a throwaway bare mirror and release root: PR and main staging deploys, production backup order, stale PR head, unknown PR, sha not on main, argument validation, venv sharing, health failure rolling back (and a first deploy having nothing to roll back to), a failed backup changing nothing, pruning to 3. `refresh-staging-data.sh` ran against the local dev PostGIS (a scratch `loam_staging`, dropped afterwards): schema from `db/init_schema.sql` + migrations, 284 public heat rows with empty `contributor_ids`, 0 users, 0 activities. shellcheck clean (info-level findings annotated). Not verified: anything that needs the Pi (systemd, sudo, docker as root, the real `pip install` on arm64, `setfacl`, tailscale).

Found on the way: `db/init_schema.sql` created `activities` before `users`, so a fresh database came out without the tables that reference `users`. `users` now comes first (the same change #40 made; the hunks are identical so the two PRs merge cleanly).

Decisions and flags:
- Production releases live under `~/loam-deploy/production`, with `current` first pointing at the existing `~/loam`, so installing changes nothing until the owner runs `provision.sh switch-production`.
- The production DB password is the development default from the public repo (`loam_dev_pw`; the Round 8 audit saw it in `docker-compose.yml`). A second Unix user (`loam-staging`) on the same machine makes that matter: the owner should rotate it (DEPLOYMENT.md A.3). `provision.sh install` also revokes `CONNECT` on the production database from PUBLIC.
- The Pi stops serving the web app on the LAN (releases carry no `frontend/dist`).
- Memory cap for staging is a guess (600M); the production API's real use could not be read from here.

## Phase 3: Firebase Hosting

`firebase.json` is a `hosting` array (`prod`, `staging`), `.firebaserc` maps the targets to the sites `thepfisters` and `loamstaging`. Production's entry is identical to before apart from `site` becoming `target` (checked by a script against `HEAD:firebase.json` while writing; the staging CSP differs only in `connect-src`: `…ts.net:8443` instead of `…ts.net`, plus `X-Robots-Tag`). `scripts/web-build-env.sh` has `WEB_ENV=staging`; `scripts/deploy-web.sh` takes `HOSTING_TARGET` (prod default, refuses anything else) and always passes `--only hosting:<target>`. Tests in `tests/test_gh45_deploy.py`; `tests/test_round8_hosting.py` and the browser stand-in server updated for the array.

`frontend/src/data/trailheads.json` committed (2 KB of OSM parking points, ODbL, no private locations; the API and the build need it on a clean checkout). #40's issue comment asked for exactly this choice (its option c); its working tree has the same file and the same `.gitignore` line.

## Phase 4: GitHub Actions

`tests.yml` (reusable, with a `ref` input; the jobs are #40's draft), `ci.yml`, `staging.yml`, `production.yml`, `dependabot.yml`; helper scripts in `scripts/deploy/ci/` (`pi-gate.sh`, `meta.sh`, `pr-comment.sh`, `hosting-release.sh`, `smoke.sh`). Every `uses:` is a full SHA (looked up with `gh api`: checkout v7.0.1, setup-node v7.1.0, setup-python v7.0.0, tailscale/github-action v4.2.0, google-github-actions/auth v3.0.0). actionlint 1.7.12 clean. `tests/test_gh45_workflows.py` guards: pinned SHAs, no `pull_request_target`, no self-hosted runners, least-privilege permissions, no secrets in CI, untrusted text only through `env:`, staging gated on owner + same repo, production main-only with rollback, hosting-only Firebase deploys, short-lived credentials. Not run for real: no secrets exist yet.

Production Hosting rollback uses the Hosting REST API (`releases.create` with the previous `versionName`), the call the console's "roll back" makes; the API half rolls back by redeploying the previous commit through the gate. If the pipeline never deployed before, there is no earlier sha to roll the API back to (the Pi's own health-check rollback still applies).

## Phase 5: Verify end to end

Done here: unit tests above; `pytest` full run, `npm run build`, `npm run lint`: see the end of this file. Waiting on the owner (DEPLOYMENT.md A–E): provisioning, the Pi dry run and rollback drill, then this PR's own staging deploy (banner after sign-in, API on 8443, nothing for signed-out users, noindex, production untouched), then the first production deploy after merge.

Final local run: `pytest -q` 353 passed (full suite, under the shared lock); `npm run build` clean; `npm run lint` has only the warnings that were already there; actionlint and shellcheck clean.
