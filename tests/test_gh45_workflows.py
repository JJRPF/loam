"""GH-45: guard rails on the GitHub Actions workflows and the CI helper scripts."""
import base64
import json
import os
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
CI = ROOT / "scripts" / "deploy" / "ci"


def text(name):
    return (ROOT / ".github" / "workflows" / name).read_text()


def test_the_expected_workflows_exist():
    assert {p.name for p in WORKFLOWS} >= {"tests.yml", "ci.yml", "staging.yml", "production.yml"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_full_sha(path):
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", path.read_text(), re.M)
    for u in uses:
        if u.startswith("./"):
            continue
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", u), f"{path.name}: {u} is not pinned to a commit"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_hardening(path):
    t = path.read_text()
    assert "pull_request_target" not in t
    assert "self-hosted" not in t and "ubuntu-latest" not in t
    assert re.search(r"^permissions:\n  contents: read", t, re.M), "least-privilege default permissions"
    assert "persist-credentials: false" in t or "checkout" not in t


def test_ci_and_tests_never_see_secrets():
    for name in ("tests.yml", "ci.yml"):
        assert "secrets." not in text(name) and "environment:" not in text(name)


def test_untrusted_text_never_goes_into_a_shell_line():
    """PR titles and branch names reach scripts through env: only, never ${{ }} inside run:."""
    for p in WORKFLOWS:
        for block in re.findall(r"run: \|?\n?(.*?)(?=\n      - |\n  \w|\Z)", p.read_text(), re.S):
            assert not re.search(r"\$\{\{\s*github\.event\.(pull_request|head_commit|issue|comment)", block), p.name


def test_staging_only_deploys_the_owners_prs_from_this_repo():
    t = text("staging.yml")
    assert t.count("github.event.pull_request.head.repo.full_name == github.repository") >= 2
    assert t.count("github.event.pull_request.user.login == 'JJRPF'") >= 2
    assert "group: loam-staging" in t and "cancel-in-progress: false" in t
    assert "types: [opened, reopened, synchronize, closed]" in t
    assert "hosting-release" not in t
    assert "--only hosting" not in t and "HOSTING_TARGET: staging" in t and "HOSTING_TARGET: prod" not in t


def test_production_deploys_main_only_and_rolls_back():
    t = text("production.yml")
    assert "branches: [main]" in t and "workflow_dispatch" in t and "is not on main" in t
    assert "group: loam-production" in t
    assert "HOSTING_TARGET: prod" in t and "HOSTING_TARGET: staging" not in t
    assert t.index("Deploy the API") < t.index("Deploy the web app") < t.index("Smoke check")
    assert "hosting-release.sh rollback" in t and "pi-gate.sh deploy \"$PREV\"" in t


def test_hosting_is_the_only_firebase_product_deployed():
    """The project is shared with family apps: every firebase deploy names --only hosting:<target>."""
    seen = 0
    for p in [*WORKFLOWS, *CI.glob("*.sh"), ROOT / "scripts" / "deploy-web.sh"]:
        for line in p.read_text().splitlines():
            if re.search(r"firebase(-tools)?[@\w.\"${}-]*\s+deploy\b", line) and not line.lstrip().startswith("#"):
                seen += 1
                assert re.search(r"--only hosting:(\$\{HOSTING_TARGET\}|prod|staging)(\s|$)", line), f"{p.name}: {line}"
    assert seen >= 1


def test_tailscale_and_google_use_short_lived_credentials():
    for name in ("staging.yml", "production.yml"):
        t = text(name)
        assert "tags: tag:ci" in t and "oauth-client-id" in t
        assert "workload_identity_provider" in t and "credentials_json" not in t
        assert "id-token: write" in t


def test_dependabot_watches_actions():
    assert "github-actions" in (ROOT / ".github" / "dependabot.yml").read_text()


# --- helper scripts --------------------------------------------------------------------------------------------

def test_meta_is_base64_json_without_empty_fields():
    env = {**os.environ, "PR_TITLE": 'T "quoted" \\ ünï', "PR_URL": "https://github.com/JJRPF/loam/pull/1", "REF": "GH-1-X", "ACTOR": "a"}
    out = subprocess.run([str(CI / "meta.sh")], env=env, capture_output=True, text=True, check=True).stdout
    assert re.fullmatch(r"[A-Za-z0-9+/=]+", out)
    assert json.loads(base64.b64decode(out)) == {"pr_title": 'T "quoted" \\ ünï', "pr_url": "https://github.com/JJRPF/loam/pull/1", "ref": "GH-1-X", "actor": "a"}


def test_meta_refuses_an_oversize_value():
    p = subprocess.run([str(CI / "meta.sh")], env={**os.environ, "PR_TITLE": "x" * 4000}, capture_output=True, text=True)
    assert p.returncode != 0 and "too long" in p.stderr


def test_pi_gate_needs_a_key_and_a_pinned_host_key(tmp_path):
    kh = tmp_path / "known_hosts"
    kh.write_text("# nothing yet\n")
    env = {k: v for k, v in os.environ.items() if k != "LOAM_DEPLOY_SSH_KEY"}
    p = subprocess.run([str(CI / "pi-gate.sh"), "status"], env={**env, "LOAM_PI_KNOWN_HOSTS": str(kh)}, capture_output=True, text=True)
    assert p.returncode != 0 and "LOAM_DEPLOY_SSH_KEY is not set" in p.stderr
    p = subprocess.run([str(CI / "pi-gate.sh"), "status"], env={**env, "LOAM_PI_KNOWN_HOSTS": str(kh), "LOAM_DEPLOY_SSH_KEY": "k"}, capture_output=True, text=True)
    assert p.returncode != 0 and "no host key" in p.stderr
    # the committed file starts as comments only, so a deploy before the owner pins the key stops here
    p = subprocess.run([str(CI / "pi-gate.sh"), "status"], env={**env, "LOAM_DEPLOY_SSH_KEY": "k"}, capture_output=True, text=True)
    assert p.returncode != 0


class _Hosting(BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        _Hosting.seen.append(("GET", self.path, self.headers.get("Authorization")))
        body = json.dumps({"releases": [{"version": {"name": "sites/thepfisters/versions/abc123"}}]}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        _Hosting.seen.append(("POST", self.path, self.headers.get("Authorization")))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *a):
        pass


@pytest.fixture
def hosting_api():
    srv = HTTPServer(("127.0.0.1", 0), _Hosting)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Hosting.seen = []
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def run_hosting(api, *args, token="tok"):
    env = {**os.environ, "LOAM_HOSTING_API": api}
    env.pop("FIREBASE_ACCESS_TOKEN", None)
    if token:
        env["FIREBASE_ACCESS_TOKEN"] = token
    return subprocess.run([str(CI / "hosting-release.sh"), *args], env=env, capture_output=True, text=True)


def test_hosting_current_reads_the_live_version(hosting_api):
    p = run_hosting(hosting_api, "current", "thepfisters")
    assert p.stdout.strip() == "sites/thepfisters/versions/abc123"
    assert _Hosting.seen == [("GET", "/sites/thepfisters/releases?pageSize=1", "Bearer tok")]


def test_hosting_rollback_posts_the_version(hosting_api):
    p = run_hosting(hosting_api, "rollback", "thepfisters", "sites/thepfisters/versions/abc123")
    assert p.returncode == 0, p.stderr
    assert _Hosting.seen == [("POST", "/sites/thepfisters/releases?versionName=sites%2Fthepfisters%2Fversions%2Fabc123", "Bearer tok")]


@pytest.mark.parametrize("args", [
    ("rollback", "thepfisters", "sites/other/versions/abc"), ("rollback", "thepfisters", "abc"),
    ("rollback", "../x", "sites/x/versions/abc"), ("current", "a b"), ("current",), ("nope",),
])
def test_hosting_rejects_odd_arguments(hosting_api, args):
    assert run_hosting(hosting_api, *args).returncode != 0 and _Hosting.seen == []


def test_hosting_needs_a_token(hosting_api):
    assert run_hosting(hosting_api, "current", "thepfisters", token="").returncode != 0
