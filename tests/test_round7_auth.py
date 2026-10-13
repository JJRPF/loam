"""Round 7 (GH-34) phase 1: Firebase ID-token verification and authorization.

Runs against the production auth dependencies (`real_auth`). Google's securetoken certs are
replaced with a locally generated key so signatures are checked for real, offline.
"""
import datetime
import time
import uuid

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from google.auth import crypt, jwt as google_jwt
from httpx import ASGITransport, AsyncClient

import app.auth as auth_module
from app.config import settings
from app.main import app

PROJECT = settings.firebase_project_id
KID = "round7-test-kid"
PROTECTED = [
    ("get", "/api/saved-routes"),
    ("get", "/api/privacy/export"),
    ("delete", "/api/privacy/account"),
]


def _key_and_cert():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "securetoken.test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    return key_pem, cert.public_bytes(serialization.Encoding.PEM).decode()


TRUSTED_KEY, TRUSTED_CERT = _key_and_cert()
ATTACKER_KEY, _ = _key_and_cert()


@pytest.fixture
def google_certs(monkeypatch, real_auth):
    from google.oauth2 import id_token

    monkeypatch.setattr(id_token, "_fetch_certs", lambda request, url: {KID: TRUSTED_CERT})
    monkeypatch.setattr(settings, "admin_emails", ["admin.round7@test.loam"])
    auth_module._known_uids.clear()
    yield


def make_token(key_pem=TRUSTED_KEY, uid=None, email="rider.round7@test.loam", email_verified=True,
               provider="google.com", aud=PROJECT, iss=None, exp_offset=3600, auth_time_offset=-60):
    now = int(time.time())
    claims = {
        "iss": iss or f"https://securetoken.google.com/{PROJECT}",
        "aud": aud,
        "sub": uid or f"fb_{uuid.uuid4().hex[:20]}",
        "user_id": uid,
        "iat": now - 30,
        "exp": now + exp_offset,
        "auth_time": now + auth_time_offset,
        "email": email,
        "email_verified": email_verified,
        "firebase": {"sign_in_provider": provider, "identities": {}},
    }
    signer = crypt.RSASigner.from_string(key_pem, key_id=KID)
    return google_jwt.encode(signer, claims).decode()


async def _call(method, path, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await getattr(client, method)(path, headers=headers)


@pytest.mark.asyncio
async def test_valid_token_is_accepted(google_certs):
    token = make_token()
    resp = await _call("get", "/api/auth/me", {"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == "rider.round7@test.loam"
    assert body["is_admin"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", PROTECTED)
async def test_forged_signature_is_401(google_certs, method, path):
    forged = make_token(key_pem=ATTACKER_KEY)
    resp = await _call(method, path, {"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", PROTECTED)
async def test_non_jwt_bearer_is_401(google_certs, method, path):
    resp = await _call(method, path, {"Authorization": "Bearer justin_default_user"})
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", PROTECTED)
async def test_x_user_id_alone_is_401(google_certs, method, path):
    resp = await _call(method, path, {"X-User-Id": "102385574010410465390"})
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", PROTECTED)
async def test_expired_token_is_401(google_certs, method, path):
    expired = make_token(exp_offset=-600)
    resp = await _call(method, path, {"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wrong_audience_and_issuer_are_401(google_certs):
    for token in (make_token(aud="another-project"), make_token(iss="https://accounts.google.com")):
        resp = await _call("get", "/api/saved-routes", {"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_unverified_email_link_user_is_401(google_certs):
    token = make_token(provider="password", email_verified=False)
    resp = await _call("get", "/api/saved-routes", {"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_missing_auth_is_401_and_anonymous_routing_allowed(google_certs):
    resp = await _call("get", "/api/saved-routes", {})
    assert resp.status_code == 401
    # Optional-auth endpoints reject a bad token instead of silently going anonymous.
    resp = await _call("get", "/api/edges/1", {"Authorization": "Bearer nope"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_x_user_id_admin_email_grants_nothing(google_certs):
    hdr = {"X-User-Id": "jjrpfister@gmail.com", "X-Dev-Key": "loam_dev_admin_2026"}
    for method, path in [("get", "/api/dev/status"), ("post", "/api/jobs/recalculate-heat"),
                         ("get", "/api/admin/restrictions"), ("post", "/api/submissions/1/approve")]:
        resp = await _call(method, path, hdr)
        assert resp.status_code == 401, (path, resp.status_code)
    # A valid non-admin token plus the old admin header is still not an admin.
    token = make_token()
    resp = await _call("get", "/api/dev/status", {**hdr, "Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_requires_verified_listed_email(google_certs):
    ok = make_token(email="admin.round7@test.loam")
    resp = await _call("get", "/api/dev/status", {"Authorization": f"Bearer {ok}"})
    assert resp.status_code == 200, resp.text
    unverified = make_token(email="admin.round7@test.loam", email_verified=False)
    resp = await _call("get", "/api/dev/status", {"Authorization": f"Bearer {unverified}"})
    assert resp.status_code == 403


def test_production_refuses_default_connector_key(monkeypatch):
    from app.config import DEFAULT_CONNECTOR_SECRET_KEY, Settings, check_production_config

    s = Settings(loam_env="production", connector_secret_key=DEFAULT_CONNECTOR_SECRET_KEY)
    with pytest.raises(RuntimeError):
        check_production_config(s)
    check_production_config(Settings(loam_env="production", connector_secret_key="x" * 40))


def test_no_header_identity_in_production_code():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    for path in list((root / "app").rglob("*.py")) + list((root / "frontend" / "src").rglob("*.ts*")):
        if path.name == "account_migration.py":  # names the legacy uids it purges
            continue
        text = path.read_text()
        for needle in ("X-User-Id", "x_user_id", "X-Dev-Key", "x_dev_key", "justin_default_user", "developer_admin_key"):
            assert needle not in text, f"{needle} in {path}"


def test_legacy_account_rekey_on_verified_login():
    """Plan 3.3: a legacy user's rows move to the Firebase uid of the same verified email."""
    from app.account_migration import claim_legacy_accounts
    from app.db import get_connection

    suffix = uuid.uuid4().hex[:8]
    legacy, fake, new_uid = f"10238557{suffix}", f"google_r7_{suffix}", f"fbuid_{suffix}"
    email = f"legacy.{suffix}@test.loam"
    with get_connection() as conn:
        with conn.cursor() as cur:
            for uid in (legacy, fake):
                cur.execute("INSERT INTO users (id, email) VALUES (%s, %s)", (uid, email))
            cur.execute(
                "INSERT INTO saved_routes (id, user_id, name, sport) VALUES (%s, %s, 'r7', 'mtb')",
                (f"route_{suffix}", legacy),
            )
            cur.execute("INSERT INTO contribution_consent (user_id, consent_given) VALUES (%s, TRUE)", (legacy,))
            cur.execute("INSERT INTO contribution_consent (user_id, consent_given) VALUES (%s, TRUE)", (fake,))
            cur.execute("INSERT INTO users (id, email, auth_provider) VALUES (%s, %s, 'firebase')", (new_uid, email))
        conn.commit()

    counts = claim_legacy_accounts(new_uid, email)
    assert counts["saved_routes"] == 1
    assert counts["users_removed"] == 2

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM saved_routes WHERE id = %s", (f"route_{suffix}",))
            assert cur.fetchone()[0] == new_uid
            cur.execute("SELECT count(*) FROM contribution_consent WHERE user_id = %s", (new_uid,))
            assert cur.fetchone()[0] == 1  # the duplicate consent row was dropped, not doubled
            cur.execute("SELECT count(*) FROM users WHERE id = ANY(%s)", ([legacy, fake],))
            assert cur.fetchone()[0] == 0
            cur.execute("DELETE FROM users WHERE id = %s", (new_uid,))
        conn.commit()
    # A second login has nothing left to claim.
    assert claim_legacy_accounts(new_uid, email) == {}
