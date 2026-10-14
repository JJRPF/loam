# Launch checklist

What has to be true for the public site, and where each item is verified. Items marked (owner) can only be done by the repository owner.

## Before the repository is made public (owner)
- [ ] Read the legal pages (`frontend/public/legal/`) and the effective date; they are plain-language drafts, not legal advice.
- [ ] Read `~/dev/loam/main/data/round8-public-audit.md` (the history and secrets audit, kept out of git) and decide what, if anything, to do about the findings.
- [ ] Make the repository public (GitHub settings). An agent never changes visibility.
- [ ] Replace `GITHUB_FEEDBACK_TOKEN` on the Pi and in the main `.env` with a new fine-grained token (Issues read/write on `JJRPF/loam` only), then revoke the old one.

## Production settings (Pi `.env`; checked by the deploy worklog)
- [ ] `APP_ENV=production`, a real `CONNECTOR_SECRET_KEY`, `ADMIN_EMAILS` set.
- [ ] `HEAT_MIN_UNIQUE_RIDERS` unset (default 3); `SEED_HEAT_PUBLIC=true`.
- [ ] `ENABLE_MIDPOINTS=false`; Strava and Trailforks flags false.
- [ ] `PUBLIC_APP_ORIGIN=https://loam.thepfisters.com`; `CORS_ORIGINS` lists that origin, the Funnel host and `http://localhost:5173`.
- [ ] No `FIREBASE_AUTH_EMULATOR_HOST` (the API refuses to start with it in production).

## Firebase (project `thepfisters` is shared: Hosting and Authentication only)
- [ ] Authentication: Google and Email link enabled; `loam.thepfisters.com` in Authorized domains (owner).
- [ ] Hosting: the custom domain `loam.thepfisters.com` is connected (owner), deploys use `--only hosting`.
- [ ] Never deploy Firestore rules or indexes, Functions or Storage from this repository.

## After each deploy
- [ ] `scripts/backup_db.sh` ran before any migration; the dump is not empty.
- [ ] `curl https://core-node.tailcd5892.ts.net/health` is healthy and `/api/config` shows `midpoints_enabled: false`.
- [ ] `BASE_URL=https://loam.thepfisters.com npx playwright test -c ../tests/browser/playwright.smoke.config.ts` (from `frontend/`) passes.
- [ ] Sign in once by hand with a real account (owner).
- [ ] The nightly backup file for last night exists on the Pi (`~/loam-backups/nightly`).

## Not done on purpose
- A known ghost-trail and good-trail list for an area you know, run through `loam_eval`, still needs the owner's local knowledge.
