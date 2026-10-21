"""GH-45: the Pi deploy scripts (scripts/deploy/pi) run for real against a throwaway mirror and release root.

Nothing here touches the network, systemd, sudo or Docker: the gate runs with a fake sudo, the runner with
LOAM_* hooks for the venv, migrations, backup, restart and health URL.
"""
import base64
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PI = ROOT / "scripts" / "deploy" / "pi"
SHA = "a" * 40


def meta(**kw):
    return base64.b64encode(json.dumps(kw).encode()).decode()


# --- the gate -------------------------------------------------------------------------------------------------

@pytest.fixture
def gate(tmp_path):
    fake_sudo = tmp_path / "sudo"
    fake_sudo.write_text('#!/bin/bash\necho "SUDO $*"\n')
    fake_sudo.chmod(0o755)

    def run(cmd):
        env = {"PATH": os.environ["PATH"], "LOAM_GATE_SUDO": str(fake_sudo), "LOAM_GATE_LOGGER": "true"}
        if cmd is not None:
            env["SSH_ORIGINAL_COMMAND"] = cmd
        p = subprocess.run(["bash", str(PI / "loam-deploy-gate")], env=env, capture_output=True, text=True)
        return p.returncode, p.stdout
    return run


M = meta(actor="x")


def test_gate_deploy(gate):
    rc, out = gate(f"deploy {SHA} {M}")
    assert rc == 0
    assert f"SUDO -n -u jjrpfister /usr/local/bin/loam-mirror-sync main" in out
    assert f"SUDO -n -u jjrpfister /usr/local/bin/loam-deploy-run production {SHA} {M}" in out


def test_gate_stage(gate):
    rc, out = gate(f"stage 45 {SHA} {M}")
    assert rc == 0
    assert "loam-mirror-sync pr" in out
    assert f"SUDO -n -u loam-staging /usr/local/bin/loam-deploy-run staging {SHA} {M} 45" in out


def test_gate_stage_main_and_status(gate):
    rc, out = gate(f"stage-main {M}")
    assert rc == 0 and f"loam-deploy-run staging main {M}" in out
    rc, out = gate("status")
    assert rc == 0 and "run status production" in out and "run status staging" in out


@pytest.mark.parametrize("cmd", [
    None, "", "bash", "ls", "status; id", "status && id", "status extra",
    f"deploy {'A' * 40} {M}", f"deploy {'a' * 39} {M}", f"deploy {'a' * 41} {M}", f"deploy {SHA}", f"deploy {SHA} ",
    f"deploy {SHA} {M} extra", f"deploy {SHA} {M};id", f"deploy {SHA} $(id)", f"deploy {SHA} {M}\nid",
    f"deploy {SHA} {'A' * 4097}", f"deploy  {SHA} {M}", f"deploy {SHA}  {M}",
    f"stage 0 {SHA} {M}", f"stage 045 {SHA} {M}", f"stage 1234567 {SHA} {M}", f"stage x {SHA} {M}",
    f"stage -1 {SHA} {M}", f"stage 5 {SHA}", f"stage 5 main {M}", "stage-main", "stage-main !!", f"stage-main {M} x",
    f"production {SHA} {M}", f"DEPLOY {SHA} {M}", f"rm -rf / {M}", f"deploy {SHA} {M}\rid",
])
def test_gate_rejects(gate, cmd):
    rc, out = gate(cmd)
    assert rc == 2 and out.strip() == "rejected"


def test_gate_accepts_the_largest_meta(gate):
    assert gate(f"deploy {SHA} {'A' * 4096}")[0] == 0


# --- deploy-info writer ---------------------------------------------------------------------------------------

def git(*args, cwd=None, **env):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", **env}).stdout.strip()


@pytest.fixture(scope="module")
def mirror(tmp_path_factory):
    """A bare mirror holding this checkout's HEAD as main, and the HEAD again as PR 7's head."""
    d = tmp_path_factory.mktemp("deploy") / "loam.git"
    git("init", "--bare", "--quiet", str(d))
    # CI checks out with depth 1, and git refuses a push from a shallow clone unless the receiver allows it.
    git("config", "receive.shallowUpdate", "true", cwd=d)
    head = git("rev-parse", "HEAD", cwd=ROOT)
    git("push", "--quiet", str(d), f"{head}:refs/heads/main", cwd=ROOT)
    git("update-ref", "refs/pull/7/head", head, cwd=d)  # one ref per shallow push; the second is local
    return d, head


def test_write_deploy_info_keeps_only_known_clean_keys(mirror, tmp_path):
    m, head = mirror
    out = tmp_path / "deploy-info.json"
    payload = meta(pr_title="Fix \x1b[31mthings", pr_url="https://github.com/JJRPF/loam/pull/7", ref="GH-7-Thing",
                   actor="jjr", run_url="https://evil.example/run", extra="dropped", author="x" * 500)
    subprocess.run(["python3", str(PI / "write-deploy-info.py"), "write", "staging", head, str(m), str(out), payload, "7"], check=True)
    info = json.loads(out.read_text())
    assert info["env"] == "staging" and info["sha"] == head and info["short_sha"] == head[:7]
    assert info["pr"] == 7 and info["pr_url"] == "https://github.com/JJRPF/loam/pull/7" and info["branch"] == "GH-7-Thing"
    assert "\x1b" not in info["pr_title"] and "extra" not in info and "run_url" not in info
    assert len(info["author"]) == 80
    assert info["commits_ahead"] == 0 and info["deployed_at"].endswith("Z")


@pytest.mark.parametrize("bad_meta", ["!!!", base64.b64encode(b"[1]").decode(), base64.b64encode(b"nope").decode()])
def test_write_deploy_info_rejects_bad_meta(mirror, tmp_path, bad_meta):
    m, head = mirror
    p = subprocess.run(["python3", str(PI / "write-deploy-info.py"), "write", "staging", head, str(m), str(tmp_path / "o.json"), bad_meta, "7"],
                       capture_output=True, text=True)
    assert p.returncode != 0 and not (tmp_path / "o.json").exists()


def test_with_env_reads_like_systemd_without_expanding(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# c\nA=1\nB='two words'\nC=pa$$word\nD=\"q\"\n\nbad line\n1X=no\n")
    out = subprocess.run([str(PI / "loam-with-env"), str(f), "env"], capture_output=True, text=True, check=True).stdout
    env = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    assert (env["A"], env["B"], env["C"], env["D"]) == ("1", "two words", "pa$$word", "q") and "1X" not in env


# --- the runner -----------------------------------------------------------------------------------------------

class _Health(BaseHTTPRequestHandler):
    """Healthy unless the release that `current` points at was deployed by an actor named "bad"."""
    current = None  # the runner's `current` symlink

    def do_GET(self):
        try:
            actor = json.loads((_Health.current / "deploy-info.json").read_text()).get("actor")
        except (OSError, ValueError, AttributeError):
            actor = None
        body = b'{"status":"degraded"}' if actor == "bad" else b'{"status":"ok"}'
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def health_server():
    srv = HTTPServer(("127.0.0.1", 0), _Health)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/health"
    srv.shutdown()


@pytest.fixture
def runner(tmp_path, mirror, health_server):
    m, head = mirror
    deploy_dir = tmp_path / "srv"
    deploy_dir.mkdir()
    os.symlink(m, deploy_dir / "loam.git")
    rel_root = tmp_path / "root"
    (rel_root / "shared").mkdir(parents=True)
    (rel_root / "shared" / ".env").write_text("APP_ENV=staging\n")
    fake_python = tmp_path / "fakepython"
    fake_python.write_text('#!/bin/bash\n# fakepython -m venv DIR\nmkdir -p "$3/bin"\n'
                           'printf "#!/bin/bash\\nexit 0\\n" > "$3/bin/pip"; cp "$3/bin/pip" "$3/bin/python"; chmod +x "$3/bin/pip" "$3/bin/python"\n')
    fake_python.chmod(0o755)
    calls = tmp_path / "calls.log"

    _Health.current = rel_root / "current"

    def run(*args, **extra_env):
        env = {
            "PATH": os.environ["PATH"], "LOAM_DEPLOY_DIR": str(deploy_dir), "LOAM_RELEASE_ROOT": str(rel_root),
            "LOAM_LIB_DIR": str(PI), "LOAM_PYTHON": str(fake_python), "LOAM_HEALTH_URL": health_server,
            "LOAM_HEALTH_WAIT_S": "2", "LOAM_RESTART_CMD": f"echo restart >> {calls}", "LOAM_MIGRATE_CMD": f"echo migrate >> {calls}",
            "LOAM_BACKUP_CMD": f"echo backup >> {calls}", "HOME": str(tmp_path),
            **extra_env,
        }
        p = subprocess.run(["bash", str(PI / "loam-deploy-run"), *args], env=env, capture_output=True, text=True)
        return p
    run.root, run.head, run.calls, run.mirror = rel_root, head, calls, m
    return run


def releases(root):
    return sorted(p.name for p in (root / "releases").glob("*") if p.is_dir())


def test_staging_pr_deploy(runner):
    p = runner("staging", runner.head, meta(pr_title="Add X", pr_url="https://github.com/JJRPF/loam/pull/7", ref="GH-7-X", actor="jjr"), "7")
    assert p.returncode == 0, p.stdout + p.stderr
    cur = (runner.root / "current").resolve()
    assert cur.parent.name == "releases" and cur.name.endswith(runner.head[:7])
    info = json.loads((cur / "deploy-info.json").read_text())
    assert info["pr"] == 7 and info["env"] == "staging" and info["sha"] == runner.head
    assert (cur / "REVISION").read_text().strip() == runner.head[:12]
    assert (cur / ".env").resolve() == (runner.root / "shared" / ".env").resolve()
    assert (cur / ".venv" / "bin" / "python").exists() and not (cur / ".git").exists()
    assert runner.calls.read_text().split() == ["migrate", "restart"]  # staging: no backup


def test_production_deploy_backs_up_first(runner):
    p = runner("production", runner.head, meta(actor="jjr"))
    assert p.returncode == 0, p.stdout + p.stderr
    assert runner.calls.read_text().split() == ["backup", "migrate", "restart"]


def test_stage_main_and_status(runner):
    p = runner("staging", "main", meta(actor="a"))
    assert p.returncode == 0, p.stdout + p.stderr
    s = runner("status", "staging")
    info = json.loads(s.stdout)
    assert info["sha"] == runner.head and "pr" not in info


def test_status_without_a_deploy_is_empty(runner):
    assert json.loads(runner("status", "production").stdout) == {}


def test_same_requirements_share_one_venv(runner):
    runner("staging", "main", meta(actor="a"))
    runner("staging", "main", meta(actor="a"))
    assert len(list((runner.root / "shared" / "venvs").iterdir())) == 1


def test_a_stale_pr_head_is_refused_and_leaves_nothing(runner):
    p = runner("staging", "b" * 40, meta(actor="a"), "7")
    assert p.returncode != 0 and "head is now" in p.stderr
    assert releases(runner.root) == [] and not (runner.root / "current").exists()


def test_an_unknown_pr_is_refused(runner):
    assert "not in the mirror" in runner("staging", runner.head, meta(actor="a"), "99").stderr


def test_production_refuses_a_sha_that_is_not_on_main(runner):
    git("push", "--quiet", str(runner.mirror), f"{runner.head}:refs/heads/side", cwd=ROOT)
    empty_tree = git("commit-tree", "-p", runner.head, "-m", "x", git("rev-parse", "HEAD^{tree}", cwd=ROOT), cwd=ROOT,
                     GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    git("push", "--quiet", str(runner.mirror), f"{empty_tree}:refs/heads/side", cwd=ROOT)
    p = runner("production", empty_tree, meta(actor="a"))
    assert p.returncode != 0 and "not on main" in p.stderr and releases(runner.root) == []


@pytest.mark.parametrize("args", [
    ("production", "nothex", "AAAA"), ("production", "a" * 40, "!!"), ("production", "a" * 40, "AAAA", "5"),
    ("staging", "main", "AAAA", "5"), ("staging", "a" * 40, "AAAA"), ("staging", "a" * 40, "AAAA", "0"),
    ("evil", "a" * 40, "AAAA"), ("status", "other"),
])
def test_runner_validates_its_arguments(runner, args):
    assert runner(*args).returncode != 0 and releases(runner.root) == []


def test_a_failed_health_check_rolls_back(runner):
    ok = runner("staging", "main", meta(actor="first"))
    assert ok.returncode == 0, ok.stdout + ok.stderr
    first = (runner.root / "current").resolve()
    bad = runner("staging", "main", meta(actor="bad"))
    assert bad.returncode == 1 and "rolling back" in bad.stderr
    assert (runner.root / "current").resolve() == first
    assert runner.calls.read_text().split().count("restart") == 3  # deploy, deploy, rollback


def test_a_failed_first_deploy_has_nothing_to_roll_back_to(runner):
    bad = runner("staging", "main", meta(actor="bad"))
    assert bad.returncode == 1 and "no earlier release" in bad.stderr


def test_a_failed_backup_changes_nothing(runner):
    ok = runner("production", runner.head, meta(actor="a"))
    first = (runner.root / "current").resolve()
    p = runner("production", runner.head, meta(actor="b"), LOAM_BACKUP_CMD="false")
    assert p.returncode != 0 and "backup failed" in p.stderr
    assert (runner.root / "current").resolve() == first and ok.returncode == 0


def test_only_three_releases_are_kept(runner):
    import time
    for i in range(5):
        assert runner("staging", "main", meta(actor=str(i))).returncode == 0
        time.sleep(1.1)  # release dirs are named by the second
    assert len(releases(runner.root)) == 3
    assert (runner.root / "current").resolve().name in releases(runner.root)


def test_the_runner_does_not_use_shell_eval_on_inputs():
    s = (PI / "loam-deploy-run").read_text()
    assert "eval " not in s
