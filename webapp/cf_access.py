"""Server-side verification of Cloudflare Access identity for admin routes.

Cloudflare Access sits in front of this app in production (see
CONTEXT-deploy-oracle.md) and, once an Access Application + policy is
configured for a path, only forwards a request here after the visitor
completes Access's own login/MFA flow. But that enforcement lives entirely
at the Cloudflare edge — nothing in this codebase stops a request from
reaching the app directly (e.g. the still-open raw-IP:port path documented
in CONTEXT-deploy-oracle.md, or a future Cloudflare misconfiguration)
without ever going through Access. So every privileged route independently
re-verifies the signed identity token Access attaches to authenticated
requests, rather than trusting "this request reached me at all" to mean it
was authorized. See CONTEXT-admin-auth.md for the full design and the
Cloudflare dashboard configuration this depends on.

Fails closed throughout: a missing, malformed, expired, or badly-signed
token, a wrong issuer/audience, or a valid token whose email isn't on the
admin allowlist — all raise HTTPException. Nothing here silently lets a
request through.
"""

import os

import jwt
from dotenv import load_dotenv
from fastapi import HTTPException, Request

load_dotenv()


def _normalize_team_domain(raw: str) -> str:
    """Strip a scheme/trailing slash some Cloudflare dashboard pages
    display alongside the team domain — pasted verbatim, that would build
    an issuer like "https://https://team.cloudflareaccess.com" and every
    otherwise-valid token would 401 with a confusing "invalid issuer".
    """
    domain = raw.strip()
    for prefix in ("https://", "http://"):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
    return domain.rstrip("/")


TEAM_DOMAIN = _normalize_team_domain(os.environ.get("CF_ACCESS_TEAM_DOMAIN", ""))
ISSUER = f"https://{TEAM_DOMAIN}" if TEAM_DOMAIN else ""
JWKS_URL = f"https://{TEAM_DOMAIN}/cdn-cgi/access/certs" if TEAM_DOMAIN else ""

# Comma-separated: a deploy protecting more than one path (e.g. one
# Access Application for /admin*, another for /api/admin*) gets a
# distinct AUD tag per Application — accept a token bearing any of them.
AUD_LIST = [a.strip() for a in os.environ.get("CF_ACCESS_AUD", "").split(",") if a.strip()]

ALLOWED_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ADMIN_ALLOWED_EMAILS", "").split(",")
    if e.strip()
}

# PyJWKClient handles fetching + caching + rotating Cloudflare's signing
# keys itself - no separate JWKS-fetch/cache code needed here. Built once
# at import time; only constructed when a team domain is actually
# configured, so an unconfigured deploy doesn't make a network call to a
# bogus URL on every request (see require_admin's early fail-closed check
# below).
_jwks_client = jwt.PyJWKClient(JWKS_URL) if JWKS_URL else None


def _extract_token(request: Request) -> str | None:
    """Cloudflare Access attaches the signed identity token to every
    request it forwards after authentication, either as a header (always
    present when the request came through Access) or a cookie (the
    browser's own Access session, sent along automatically). Prefer the
    header; fall back to the cookie.
    """
    header = request.headers.get("cf-access-jwt-assertion")
    if header:
        return header
    return request.cookies.get("CF_Authorization")


def require_admin(request: Request) -> dict:
    """FastAPI dependency: verify the Cloudflare Access JWT on THIS
    request and check the identity against the admin allowlist.

    Add this as a per-route `Depends(require_admin)`, or via a router's
    `dependencies=[Depends(require_admin)]` so every route added to it is
    covered automatically — never rely on the /admin page having been
    reached first, since API routes are directly callable without it.

    Returns {"email": ..., "sub": ...} on success. Raises HTTPException
    (401 for anything about the token itself, 403 for a valid token whose
    identity isn't authorized) otherwise.
    """
    if not TEAM_DOMAIN or not AUD_LIST:
        # Not configured - fail closed rather than silently accepting
        # every request (or, worse, crashing on a None JWKS client).
        raise HTTPException(status_code=401, detail="Admin access is not configured on this server.")

    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Cloudflare Access token.")

    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=AUD_LIST,
            issuer=ISSUER,
            # PyJWT only checks exp/iss/aud when the claim is present -
            # without `require`, a token simply missing `exp` would pass
            # unexpired by default. The task calls for signature, issuer,
            # audience, *and* expiration to all be verified, so make all
            # three mandatory rather than conditionally-checked.
            options={"require": ["exp", "iss", "aud"]},
        )
    except jwt.PyJWTError as e:
        # Covers bad signature, wrong iss/aud, expired/not-yet-valid
        # tokens, and (via PyJWKClientError, a PyJWTError subclass) a
        # failed JWKS fetch - all fail closed as 401, deliberately, not a
        # 502/503 that could read as "try again" instead of "not
        # authorized".
        raise HTTPException(status_code=401, detail=f"Invalid Cloudflare Access token: {e}")

    email = (claims.get("email") or "").strip().lower()
    # Cloudflare service tokens (non-interactive, e.g. `common_name`
    # claim instead of `email`) end up here with no email - rejected by
    # design, since only the two named interactive users are authorized.
    if not email or email not in ALLOWED_EMAILS:
        raise HTTPException(status_code=403, detail="Not authorized for admin access.")

    return {"email": email, "sub": claims.get("sub")}
