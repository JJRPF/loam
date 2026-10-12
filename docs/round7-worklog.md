# Round 7 work log (GH-34)

Running log for the plan in `docs/round7-plan.md`: what was done, what was measured, and every deviation with its reason.

## Setup (2026-10-12)

- Worktree `GH-34-Round7` from `main` at `ff18e7b`. `.venv` links to main's venv (Python 3.14.7).
- Local stack: the existing `loam-postgis` and `loam-graphhopper` containers (mounts under `~/dev/loam/main/data`) were stopped; `docker compose up` from the worktree failed on the container-name conflict, so I started the existing containers with `docker start` instead. Same images and volumes, so this matches the plan's intent.
- Baseline: `PYTHONPATH=. pytest -q` gives 98 passed once the frontend is built (`npm ci && npm run build`). Without a build, 3 static-serving tests fail with 404.
- Firebase (project `thepfisters`), checked with read-only REST calls: `firebase.googleapis.com/v1beta1/projects/thepfisters/webApps` returns `{}`, so no web app is registered. `identitytoolkit admin/v2 .../config` returns `404 CONFIGURATION_NOT_FOUND`, which means Firebase Authentication hasn't been initialized on the project yet ("Get started" in the console). Per plan 3.1 and 12, I didn't create either; both are manual steps for the user. The code is built against env config and can't be checked with a live login until they're done.
- Pi (`core-node`) is reachable over SSH with a key: 7 GB RAM, 76 GB free on `/`, `loam-postgis` and `loam-graphhopper` running.
