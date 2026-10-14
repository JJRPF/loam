"""Firebase Auth ID-token verification and FastAPI auth dependencies.

Identity comes only from a verified Firebase ID token in `Authorization: Bearer`.
There is no header-based identity, no unsigned-token parsing and no default user.
Tests inject users through `app.dependency_overrides` (see tests/conftest.py).
"""
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException, status

from app.config import settings

logger = logging.getLogger("loam.auth")

# Firebase email-link sign-in reports `sign_in_provider == "password"`.
EMAIL_LINK_PROVIDERS = {"password", "emailLink"}
CLOCK_SKEW_SECONDS = 10


class AuthError(Exception):
    """The presented token is missing, malformed, forged, expired or for another project."""


@dataclass(frozen=True)
class AuthUser:
    uid: str
    email: Optional[str]
    email_verified: bool
    name: Optional[str]
    picture: Optional[str]
    sign_in_provider: Optional[str]
    is_admin: bool


_request_lock = threading.Lock()
_google_request = None


def _get_google_request():
    """A google-auth transport whose HTTP session caches Google's public certs (Cache-Control)."""
    global _google_request
    with _request_lock:
        if _google_request is None:
            import requests
            import cachecontrol
            import google.auth.transport.requests

            session = cachecontrol.CacheControl(requests.session())
            _google_request = google.auth.transport.requests.Request(session=session)
        return _google_request


def is_admin_email(email: Optional[str], email_verified: bool) -> bool:
    if not email or not email_verified:
        return False
    return email.strip().lower() in {e.lower() for e in settings.admin_emails}


def _verify_emulator_token(token: str, project: str) -> Dict[str, Any]:
    """Firebase Auth emulator tokens are unsigned. Reached only when FIREBASE_AUTH_EMULATOR_HOST is set,
    which check_auth_emulator_config allows only off production and on loopback."""
    import base64
    import json

    def part(i: int) -> Dict[str, Any]:
        raw = token.split(".")[i]
        return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))

    try:
        header, claims = part(0), part(1)
    except Exception:
        raise AuthError("Invalid emulator token") from None
    if header.get("alg") != "none":
        raise AuthError("Invalid emulator token")  # a real signed token is not an emulator token
    if claims.get("aud") != project or claims.get("iss") != f"https://securetoken.google.com/{project}":
        raise AuthError("Invalid ID token audience or issuer")
    exp = claims.get("exp")
    sub = claims.get("sub")
    if not isinstance(exp, (int, float)) or exp < time.time() or not isinstance(sub, str) or not sub:
        raise AuthError("Invalid emulator token")
    return claims


def verify_firebase_token(token: str) -> Dict[str, Any]:
    """Verifies a Firebase ID token and returns its claims.

    Checks the RS256 signature against Google's securetoken certs, `aud` (project id),
    `iss` (https://securetoken.google.com/<project>), `exp`/`iat` and `auth_time`.
    """
    from google.oauth2 import id_token as google_id_token

    token = (token or "").strip()
    if not token or token.count(".") != 2:
        raise AuthError("Bearer token is not a JWT")
    project = settings.firebase_project_id
    if settings.auth_emulator_host:
        return _verify_emulator_token(token, project)
    try:
        claims = google_id_token.verify_firebase_token(
            token, _get_google_request(), audience=project, clock_skew_in_seconds=CLOCK_SKEW_SECONDS
        )
    except Exception as e:  # signature, expiry, audience or malformed token
        raise AuthError(f"Invalid ID token: {type(e).__name__}") from None
    if not claims:
        raise AuthError("Invalid ID token")
    if claims.get("iss") != f"https://securetoken.google.com/{project}":
        raise AuthError("Invalid ID token issuer")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub.strip():
        raise AuthError("ID token has no subject")
    auth_time = claims.get("auth_time")
    if not isinstance(auth_time, (int, float)) or auth_time > time.time() + CLOCK_SKEW_SECONDS:
        raise AuthError("ID token has an invalid auth_time")
    provider = (claims.get("firebase") or {}).get("sign_in_provider")
    if provider in EMAIL_LINK_PROVIDERS and claims.get("email_verified") is not True:
        raise AuthError("Email address is not verified")
    return claims


def user_from_claims(claims: Dict[str, Any]) -> AuthUser:
    email = claims.get("email")
    email_verified = claims.get("email_verified") is True
    return AuthUser(
        uid=claims["sub"],
        email=email,
        email_verified=email_verified,
        name=claims.get("name"),
        picture=claims.get("picture"),
        sign_in_provider=(claims.get("firebase") or {}).get("sign_in_provider"),
        is_admin=is_admin_email(email, email_verified),
    )


_known_uids: set = set()
_known_lock = threading.Lock()


def _register_user(user: AuthUser) -> None:
    """On the first request from a uid in this process: upsert the users row and, if a legacy
    account has the same verified email, re-key its rows to this uid (plan 3.3)."""
    with _known_lock:
        if user.uid in _known_uids:
            return
    from app.account_migration import claim_legacy_accounts, mark_firebase_user
    from app.db import ensure_user_exists

    ensure_user_exists(user.uid, email=user.email, display_name=user.name)
    try:
        if user.email and user.email_verified:
            claim_legacy_accounts(user.uid, user.email)
        else:
            mark_firebase_user(user.uid)
    except Exception:
        logger.exception("Legacy account claim failed for uid=%s", user.uid)
    with _known_lock:
        _known_uids.add(user.uid)


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if authorization is None:
        return None
    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


def _authenticate(token: str) -> AuthUser:
    try:
        claims = verify_firebase_token(token)
    except AuthError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = user_from_claims(claims)
    _register_user(user)
    return user


def get_current_user(authorization: Optional[str] = Header(None)) -> AuthUser:
    """Required auth: 401 when the header is missing or the token is invalid."""
    token = _bearer(authorization)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _authenticate(token)


def get_optional_user(authorization: Optional[str] = Header(None)) -> Optional[AuthUser]:
    """Optional auth: None without a header; 401 when a header is present but invalid."""
    token = _bearer(authorization)
    if token is None:
        return None
    return _authenticate(token)


def get_admin_user(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    """Admin auth: a verified token whose verified email is listed in ADMIN_EMAILS."""
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
