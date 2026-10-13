#!/usr/bin/env python3
"""Upload stripped Garmin tracks (scripts/strip_garmin_export.py output) to Loam's heat layer.

HTTP mode (the normal path, plan 7.2): POSTs batches of <= 25 tracks to
`/api/admin/heat/bulk-import` with your Firebase ID token (admin only). The token is read from
--token-file (keep it outside the repo) or pasted at the prompt; it is never printed or saved.

Direct mode (--direct --user-id UID): runs the same server-side import in-process against the
database in DATABASE_URL. For the local stack, or on the Pi before Firebase sign-in is set up.

Progress is kept in <dir>/upload_state.<target>.json, so a rerun resumes where it stopped.

    python -m scripts.upload_stripped --dir ~/dev/loam/main/data/garmin-stripped --url https://<host> --token-file ~/token
    python -m scripts.upload_stripped --dir ~/dev/loam/main/data/garmin-stripped --direct --user-id <uid>
"""
import argparse
import asyncio
import getpass
import glob
import hashlib
import json
import os
import sys

BATCH = 25


def load_tracks(directory):
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        name = os.path.basename(path)
        if name == "manifest.json" or name.startswith("upload_state"):
            continue
        with open(path) as f:
            yield json.load(f)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--url", help="Loam base URL for HTTP mode")
    ap.add_argument("--token-file", help="file holding a Firebase ID token (outside the repo)")
    ap.add_argument("--direct", action="store_true", help="import in-process against DATABASE_URL")
    ap.add_argument("--user-id", help="direct mode: the user the activities belong to")
    args = ap.parse_args()
    directory = os.path.expanduser(args.dir)
    if args.direct == bool(args.url):
        ap.error("use exactly one of --url (HTTP) or --direct")
    if args.direct and not args.user_id:
        ap.error("--direct needs --user-id")

    target = "direct-" + hashlib.sha256(args.user_id.encode()).hexdigest()[:8] if args.direct else \
        hashlib.sha256(args.url.encode()).hexdigest()[:8]
    state_path = os.path.join(directory, f"upload_state.{target}.json")
    state = json.load(open(state_path)) if os.path.exists(state_path) else {}
    pending = [t for t in load_tracks(directory) if state.get(str(t["activity_id"])) not in ("matched", "skipped")]
    print(f"{len(pending)} tracks to upload ({len(state)} already processed)", file=sys.stderr)

    if args.direct:
        from app.heat_import import import_tracks

        def send(batch):
            return asyncio.run(import_tracks(args.user_id, batch))
    else:
        import httpx
        token = open(os.path.expanduser(args.token_file)).read().strip() if args.token_file else \
            getpass.getpass("Firebase ID token: ").strip()
        client = httpx.Client(base_url=args.url.rstrip("/"), timeout=600.0,
                              headers={"Authorization": f"Bearer {token}"})

        def send(batch):
            r = client.post("/api/admin/heat/bulk-import", json={"tracks": batch})
            if r.status_code == 401:
                sys.exit("401: the token is invalid or expired; get a fresh one and rerun (progress is saved)")
            if r.status_code == 403:
                sys.exit("403: this account is not an admin")
            r.raise_for_status()
            return r.json()

    totals = {"matched": 0, "failed": 0, "skipped": 0}
    seeds = 0
    for i in range(0, len(pending), BATCH):
        batch = pending[i:i + BATCH]
        res = send(batch)
        for r in res["results"]:
            state[str(r["activity_id"])] = r["status"]
            totals[r["status"]] += 1
            seeds += r.get("seed") == "stored"
        with open(state_path, "w") as f:
            json.dump(state, f)
        print(f"batch {i // BATCH + 1}: {res['matched']} matched, {res['failed']} failed, {res['skipped']} skipped",
              file=sys.stderr)
    print(json.dumps({**totals, "seed_loops_stored": seeds}))


if __name__ == "__main__":
    main()
