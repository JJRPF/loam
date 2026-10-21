# Deployment

Loam has two halves, and every deploy does both, API first:

| Half | Where | Staging | Production |
|---|---|---|---|
| API | Raspberry Pi `core-node` (FastAPI `loam-api`, PostGIS, GraphHopper) behind a Tailscale Funnel | `loam-api-staging` on :8086, public as `https://core-node.tailcd5892.ts.net:8443` | `loam-api` on :8085, public as `https://core-node.tailcd5892.ts.net` |
| Web app | Firebase Hosting, project `thepfisters` (shared with family apps: **hosting only, ever**) | site `loamstaging` → https://loamstaging.thepfisters.com | site `thepfisters` → https://loam.thepfisters.com |

## What happens

- **Every PR:** `ci.yml` runs the tests (`tests.yml`: frontend lint and build, API tests against PostGIS).
- **A PR from the owner, from a branch of this repo** (never a fork): `staging.yml` runs the tests, builds the web app in staging mode, deploys the PR's head to the Pi's staging API, then to the `loamstaging` site, and comments the link on the PR. A newer push replaces it (`concurrency`; the Pi also refuses a head that is no longer the PR's). Signed in, the page shows a strip with the PR, branch, commit and commits ahead of main (`GET /api/version`, sign-in required); signed out it shows nothing about the deploy. Closing or merging the PR puts staging back on main if it still shows that PR.
- **A merge to main** (any PR): `production.yml` runs the tests, deploys the API (database backup, migrations, restart, health check; the Pi rolls itself back if the check fails), then Hosting, then a smoke check. If the smoke check fails, Hosting goes back to the release that was live before and the API to the commit that was deployed before. **Run workflow** redeploys or rolls back to any commit on main.

There is no self-hosted runner: the repo is public, so a runner on the Pi would run strangers' code. GitHub reaches the Pi over Tailscale (an ephemeral `tag:ci` node), by SSH as `loam-deployer`, whose single key can run only the deploy gate's four commands.

## Staging is not production

- Its **own database** (`loam_staging`, own role) with production's schema and only public, non-personal data: trail geometry, restrictions, coverage cells, and heat that is already public with contributor ids removed. **Never** users, activities, GPS, privacy zones, saved routes, reports or connected services (`scripts/deploy/pi/refresh-staging-data.sh` lists both sets). Staging users sign in with Firebase and start empty. Changing that rule is the owner's call.
- The API refuses to start with `APP_ENV=staging` if `DATABASE_URL` is the production database, `GITHUB_FEEDBACK_TOKEN` is set (staging must not file real issues), Strava or Trailforks is enabled, `CONNECTOR_SECRET_KEY` is the development default, or `CORS_ORIGINS` / `PUBLIC_APP_ORIGIN` name a production origin. Tests: `tests/test_gh45_deploy.py`.
- `noindex` everywhere: `X-Robots-Tag` on the API and on the `loamstaging` site, `robots.txt` that disallows all, no sitemap.
- Its API unit is capped (`MemoryMax=600M`, a guess: see Memory below), runs as its own user, and cannot read production's `.env`, code or backups.

## The owner's steps (nothing below is done by the agents)

Every step changes something outside the repo. Do them in this order; the PR's own staging deploy fails with a clear message until A–E are done.

### A. The Pi (as root on `core-node`)

1. On a trusted machine make the CI key: `ssh-keygen -t ed25519 -N '' -C loam-ci-deploy -f loam-ci-deploy`. The private file becomes the GitHub secret `LOAM_DEPLOY_SSH_KEY` (step F); only `loam-ci-deploy.pub` goes to the Pi. Delete the private file afterwards.
2. Get this PR's scripts onto the Pi (the repo is public): `git clone --depth 1 -b GH-45-AutoDeploy https://github.com/JJRPF/loam.git /tmp/loam-deploy-src` (after the merge, `main`).
3. `sudo /tmp/loam-deploy-src/scripts/deploy/pi/provision.sh check`: tools, users, free memory, the funnel, the production unit. It warns if production's `DATABASE_URL` still has the development password `loam_dev_pw`, which is in this public repo: **rotate it** (`ALTER ROLE loam PASSWORD '...'` in the container, then the same in `~/loam/.env`, then `sudo systemctl restart loam-api` and the nightly backup's `PGPASSWORD`), because the staging Unix user could otherwise log in to the production database with it. `provision.sh install` also revokes `CONNECT` on the production database from everyone but its owner.
4. `sudo /tmp/loam-deploy-src/scripts/deploy/pi/provision.sh install --deploy-pubkey loam-ci-deploy.pub`. It creates the users `loam-deployer` (forced command only) and `loam-staging`, the shared lock and bare mirror in `/srv/loam-deploy`, the root-owned scripts in `/usr/local/bin` and `/usr/local/lib/loam-deploy`, `/etc/sudoers.d/loam-deploy` (checked with `visudo -cf`), the release directories, the staging database, role and `.env` (secrets generated on the Pi, `0600`, never printed), read access for staging to the elevation tiles only, and the `loam-api-staging` unit. It does **not** touch the running production API. Rerunnable.
5. `sudo /tmp/loam-deploy-src/scripts/deploy/pi/refresh-staging-data.sh`: fills `loam_staging` (read-only on production). Rerun it whenever staging should see newer trails. It stops the staging API while it rebuilds, so run it when nobody is looking at staging. The nightly heat job on staging would recompute heat from its empty visit table, so staging's heat layer is whatever this script last copied until then.
6. Pin the Pi's host key: on the Pi, `cat /etc/ssh/ssh_host_ed25519_key.pub`; commit `.github/pi_known_hosts` as one line `core-node.tailcd5892.ts.net ssh-ed25519 AAAA...` (public data).
7. Funnel for staging: `tailscale funnel status` first. Funnel only exposes 443, 8443 and 10000 on the node's name, so staging is on **8443**: `sudo tailscale funnel --bg --https=8443 http://127.0.0.1:8086`. Production's funnel on 443 is untouched.
8. **Memory.** The Pi also runs GraphHopper (`-Xmx2g`) and PostGIS. `provision.sh check` prints free memory and the production API's current use; if `loam-api` uses less than half of 600M, lower `STAGING_MEMORY_MAX` (environment variable of `install`) or raise it if staging gets OOM-killed (`journalctl -u loam-api-staging`).
9. Do the first staging deploy (this PR's workflow, or by hand: `sudo -u loam-staging /usr/local/bin/loam-deploy-run staging main <meta>` with `<meta>` = `echo '{}' | base64`), check `curl http://127.0.0.1:8086/health`.
10. **The one production-changing step**, when staging works: `sudo .../provision.sh switch-production`. It shows the unit, writes a drop-in that points `loam-api` at `~/loam-deploy/production/current` (which starts as a link to today's `~/loam`, so nothing moves), restarts, and removes the drop-in again if `/health` is not ok within a minute. After the first production deploy the code lives in `~/loam-deploy/production/releases/`; `~/loam` stays as the first rollback target and can be removed later.

Rollback drill (staging only): `sudo -u loam-staging env LOAM_HEALTH_URL=http://127.0.0.1:1/health LOAM_HEALTH_WAIT_S=5 /usr/local/bin/loam-deploy-run staging main "$(echo '{}' | base64)"` deploys main, fails the health check on purpose and must put the previous release back (exit 1, "rolled back").

### B. Tailscale

- Admin console → Settings → OAuth clients: create one with scope **Auth Keys (write)** limited to `tag:ci`. The id and secret become `TS_OAUTH_CLIENT_ID` and `TS_OAUTH_SECRET`.
- ACL: `tag:ci` may reach only the Pi's SSH port. Merge into your policy (adapt names):

```json
"tagOwners": { "tag:ci": ["autogroup:admin"] },
"acls": [ { "action": "accept", "src": ["tag:ci"], "dst": ["core-node:22"] } ]
```

### C. Firebase Hosting (project `thepfisters`; hosting only)

1. `npx firebase-tools@15.33.0 hosting:sites:create loamstaging --project thepfisters`
2. Console → Hosting → site `loamstaging` → Add custom domain `loamstaging.thepfisters.com`. Firebase shows the DNS record to add (usually an `A` and a `TXT`, or a `CNAME`); add exactly that in Cloud DNS zone `thepfisters-com`. Wait for the certificate.
3. Firebase Auth → Settings → Authorized domains: add `loamstaging.thepfisters.com`.
4. Google Cloud console → APIs & Services → Credentials → the web OAuth client: add the authorized redirect URI `https://loamstaging.thepfisters.com/__/auth/handler`.
5. `.firebaserc` maps target `prod` to site `thepfisters` and `staging` to `loamstaging` (already committed).

### D. Keyless Google access for Actions (Workload Identity Federation, no JSON keys)

```bash
PROJECT=thepfisters; PNUM=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
gcloud iam service-accounts create loam-hosting-deploy --project $PROJECT --display-name "Loam Hosting deploys (GitHub Actions)"
SA=loam-hosting-deploy@$PROJECT.iam.gserviceaccount.com
gcloud projects add-iam-policy-binding $PROJECT --member serviceAccount:$SA --role roles/firebasehosting.admin
gcloud iam workload-identity-pools create github --project $PROJECT --location global --display-name "GitHub Actions"
gcloud iam workload-identity-pools providers create-oidc loam --project $PROJECT --location global --workload-identity-pool github \
  --issuer-uri https://token.actions.githubusercontent.com \
  --attribute-mapping 'google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.environment=assertion.environment' \
  --attribute-condition "assertion.repository == 'JJRPF/loam' && assertion.environment in ['staging','production']"
gcloud iam service-accounts add-iam-policy-binding $SA --project $PROJECT --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/$PNUM/locations/global/workloadIdentityPools/github/attribute.repository/JJRPF/loam"
echo "WIF_PROVIDER=projects/$PNUM/locations/global/workloadIdentityPools/github/providers/loam"; echo "WIF_SERVICE_ACCOUNT=$SA"
```

The service account has **only** `roles/firebasehosting.admin`. If a deploy reports a missing `serviceusage` permission, add `roles/serviceusage.serviceUsageConsumer` and nothing broader (not verified here: it has not been run against the project).

### E. GitHub (repository JJRPF/loam → Settings)

- Environments `staging` and `production`. On `production`: deployment branches = `main` only; optionally a required reviewer, which makes every merge wait for your click.
- Secrets: `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`, `LOAM_DEPLOY_SSH_KEY`.
- Variables: `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT` (from D), and the public Firebase web config the build needs (Firebase console → Project settings → Your apps → Loam): `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_APP_ID`.
- Optionally require the `CI / tests` checks on `main`.

## What changed for the Pi

- Code lives in `~/loam-deploy/<env>/releases/<time>-<sha>` (3 kept), `current` is a symlink, `.env` and `data/` are shared links, one venv per `requirements.txt` hash. No `.git` in a release; `REVISION` holds the commit (bug reports already read it).
- **The Pi no longer serves the web app on the LAN.** The old deploy synced a built `frontend/dist` into `~/loam` and the API mounted it; releases are code only, and the web app comes from Firebase Hosting. The mount is still there and serves a `dist` if one exists.
- `frontend/src/data/trailheads.json` (public OSM parking points) is now committed, because the API reads it and CI builds need it.
- `scripts/deploy-pi.sh` is gone; `scripts/deploy-web.sh` remains as a manual Hosting deploy (`HOSTING_TARGET=prod|staging`) for an emergency.

## Limits to know

- Migrations are additive in this repo, so rolling the code back does not roll the database back; the pre-deploy dump (`~/loam-deploy/production/backups`, last five) is for that: `pg_restore --clean`.
- The smoke check runs from a GitHub runner that is on the tailnet, so it reaches the Funnel's name by its tailnet address, not the public path. The web half of the check is public.
- The first production deploy after the owner steps ships everything merged since `6f55210` (the last manual deploy): only the README and this work, as of writing.
- Only commits on `main` can be deployed to production, by hash. Staging deploys only a PR's current head.
