#!/usr/bin/env python3
"""Writes or prints deploy-info.json, which app/deploy_info.py serves from /api/version.

  write-deploy-info.py write <env> <sha> <mirror.git> <out-file> <meta-b64> [<pr>]
  write-deploy-info.py status <file>

The meta comes from the caller (the GitHub Actions workflow, through the gate), so only known keys are kept,
trimmed, and the links must be https://github.com/... URLs. commits_ahead counts the commits the deployed sha
has that main does not (0 for main itself).
"""
import base64
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

META_KEYS = {"pr_title": 200, "pr_url": 300, "ref": 200, "author": 80, "actor": 80, "run_url": 300}
URL_KEYS = ("pr_url", "run_url")


def clean_meta(meta_b64: str) -> dict:
    try:
        raw = json.loads(base64.b64decode(meta_b64, validate=True))
    except (ValueError, TypeError):
        raise SystemExit("bad meta")
    if not isinstance(raw, dict):
        raise SystemExit("bad meta")
    out = {}
    for key, limit in META_KEYS.items():
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            continue
        value = "".join(c for c in value if c.isprintable())[:limit]
        if key in URL_KEYS and not re.match(r"^https://github\.com/[A-Za-z0-9._/-]+$", value):
            continue
        out[key] = value
    return out


def commits_ahead(mirror: str, sha: str):
    try:
        out = subprocess.run(["git", "--git-dir", mirror, "rev-list", "--count", f"refs/heads/main..{sha}"],
                             capture_output=True, text=True, timeout=30, check=True).stdout.strip()
        return int(out)
    except (subprocess.SubprocessError, ValueError):
        return None


def write(env, sha, mirror, out_file, meta_b64, pr):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise SystemExit("bad sha")
    meta = clean_meta(meta_b64)
    info = {
        "env": env,
        "sha": sha,
        "short_sha": sha[:7],
        "branch": meta.get("ref"),
        **meta,
        "commits_ahead": commits_ahead(mirror, sha),
        "deployed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if pr:
        info["pr"] = int(pr)
        info["pr_title"] = meta.get("pr_title")
        info["pr_url"] = meta.get("pr_url")
    tmp = out_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in info.items() if v is not None}, f, indent=2)
        f.write("\n")
    os.replace(tmp, out_file)


def main(argv):
    if len(argv) >= 3 and argv[1] == "status":
        try:
            with open(argv[2], encoding="utf-8") as f:
                print(json.dumps(json.load(f), separators=(",", ":")))
        except (OSError, ValueError):
            print("{}")
        return
    if len(argv) in (7, 8) and argv[1] == "write":
        write(argv[2], argv[3], argv[4], argv[5], argv[6], argv[7] if len(argv) == 8 else "")
        return
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
