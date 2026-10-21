"""What this server is running: the environment, commit and (on staging) the pull request.

`loam-deploy-run` writes `deploy-info.json` into the release directory (scripts/deploy/pi/write-deploy-info.py).
`DEPLOY_INFO_FILE` overrides the path (tests). Without the file the answer falls back to the environment and the
commit from reports.git_sha(), so a laptop checkout still answers.
"""
import json
import os
from typing import Any, Dict, Optional

from app.config import settings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_cache: Dict[str, Any] = {"file": None, "mtime": None, "info": None}


def deploy_info_path() -> str:
    return os.getenv("DEPLOY_INFO_FILE") or os.path.join(ROOT, "deploy-info.json")


def _read_file() -> Optional[Dict[str, Any]]:
    """The deploy file, re-read when its mtime changes. None when absent or unreadable."""
    path = deploy_info_path()
    try:
        mtime = os.stat(path).st_mtime_ns
        if _cache["file"] != path or _cache["mtime"] != mtime:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            _cache.update(file=path, mtime=mtime, info=data if isinstance(data, dict) else None)
        return _cache["info"]
    except (OSError, ValueError):
        return None


def get_deploy_info() -> Dict[str, Any]:
    from app.reports import git_sha

    info = dict(_read_file() or {})
    info["env"] = settings.loam_env
    if not info.get("sha"):
        sha = git_sha()
        info["sha"] = None if sha == "unknown" else sha
    sha = info["sha"]
    info["short_sha"] = sha[:7] if sha else None
    return info
