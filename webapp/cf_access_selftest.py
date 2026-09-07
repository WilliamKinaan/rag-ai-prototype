"""Standalone self-test for webapp/cf_access.py's verification logic.

Not a pytest suite (none exists in this repo) - just a script you run
directly:

    python webapp/cf_access_selftest.py

Exercises the actual crypto path (signature / iss / aud / exp) with a
throwaway RSA keypair and a monkeypatched JWKS lookup - no real Cloudflare
account or network access needed. This matters because a plain "no token
-> 401" curl check only proves the *unconfigured* fail-closed branch
fires; it never runs jwt.decode()'s actual claim checks, so a bug there
(wrong claim name, swapped iss/aud, etc.) would otherwise only surface
later as "my valid Cloudflare token still 401s", debugged live against
the deployed instance.

Note: cf_access.py has no email allowlist of its own (see its module
docstring) - authorization is delegated entirely to the Cloudflare Access
policy on the Application, which is what actually decides who gets a
token in the first place. So there's no "non-allowlisted email" case to
test here; a token that passes verification is, by construction, one
Cloudflare already approved.

Exits non-zero if any check fails.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import cf_access  # noqa: E402

TEAM_DOMAIN = "test-team.cloudflareaccess.com"
AUD = "test-aud-tag"
KID = "test-key-1"

# Fixed test config, independent of whatever (if anything) is in .env -
# require_admin reads these module attributes, not the environment
# directly, so overwriting them here is enough to isolate the test.
cf_access.TEAM_DOMAIN = TEAM_DOMAIN
cf_access.ISSUER = f"https://{TEAM_DOMAIN}"
cf_access.AUD_LIST = [AUD]

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJWKSClient:
    """Stands in for jwt.PyJWKClient - always returns our test key, so no
    real network/JWKS fetch happens.
    """

    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey(_private_key.public_key())


cf_access._jwks_client = _FakeJWKSClient()


def _make_token(*, aud=AUD, iss=None, email="admin@example.com", exp_delta=3600, sign_with=None, omit_exp=False):
    now = int(time.time())
    claims = {
        "aud": aud,
        "iss": iss if iss is not None else cf_access.ISSUER,
        "email": email,
        "sub": "test-sub",
        "iat": now,
    }
    if not omit_exp:
        claims["exp"] = now + exp_delta
    key = sign_with if sign_with is not None else _private_key
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": KID})


class _FakeRequest:
    """Minimal stand-in for fastapi.Request - require_admin only reads
    .headers.get(...) / .cookies.get(...), both of which a plain dict
    already supports.
    """

    def __init__(self, token=None, via="header"):
        self.headers = {}
        self.cookies = {}
        if token is not None:
            if via == "header":
                self.headers["cf-access-jwt-assertion"] = token
            else:
                self.cookies["CF_Authorization"] = token


def expect_status(request, expected_status):
    try:
        cf_access.require_admin(request)
    except HTTPException as e:
        assert e.status_code == expected_status, f"expected {expected_status}, got {e.status_code}: {e.detail}"
        return
    raise AssertionError(f"expected HTTPException {expected_status}, got no exception")


def test_valid_token():
    identity = cf_access.require_admin(_FakeRequest(_make_token(email="admin@example.com")))
    assert identity["email"] == "admin@example.com", identity


def test_valid_token_via_cookie():
    identity = cf_access.require_admin(_FakeRequest(_make_token(), via="cookie"))
    assert identity["email"], identity


def test_wrong_aud():
    expect_status(_FakeRequest(_make_token(aud="someone-elses-app")), 401)


def test_wrong_iss():
    expect_status(_FakeRequest(_make_token(iss="https://not-our-team.cloudflareaccess.com")), 401)


def test_expired():
    expect_status(_FakeRequest(_make_token(exp_delta=-60)), 401)


def test_missing_exp_claim():
    # PyJWT only checks exp when the claim is present - without the
    # `require` option in cf_access.py, a token that simply omits `exp`
    # would otherwise sail through as "not expired". Guards against that
    # regressing.
    expect_status(_FakeRequest(_make_token(omit_exp=True)), 401)


def test_tampered_signature():
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    expect_status(_FakeRequest(_make_token(sign_with=other_key)), 401)


def test_missing_token():
    expect_status(_FakeRequest(token=None), 401)


def test_multi_aud_second_tag_accepted():
    # Mirrors the real deploy: if this ever protects more than one path,
    # each Access Application gets its own AUD, both configured into
    # CF_ACCESS_AUD. A token bearing either must be accepted - if PyJWT's
    # list semantics were ever "all of" instead of "any of", every
    # request to one of the two Applications would 401 in production.
    other_aud = "second-aud-tag"
    original_aud_list = cf_access.AUD_LIST
    cf_access.AUD_LIST = [AUD, other_aud]
    try:
        identity = cf_access.require_admin(_FakeRequest(_make_token(aud=other_aud)))
        assert identity["email"], identity
        expect_status(_FakeRequest(_make_token(aud="some-unrelated-aud")), 401)
    finally:
        cf_access.AUD_LIST = original_aud_list


CHECKS = [
    ("valid token -> identity", test_valid_token),
    ("valid token via cookie -> identity", test_valid_token_via_cookie),
    ("wrong aud -> 401", test_wrong_aud),
    ("wrong iss -> 401", test_wrong_iss),
    ("expired token -> 401", test_expired),
    ("missing exp claim -> 401", test_missing_exp_claim),
    ("tampered signature -> 401", test_tampered_signature),
    ("missing token -> 401", test_missing_token),
    ("multi-AUD config accepts either tag, rejects a third -> 401", test_multi_aud_second_tag_accepted),
]


def main() -> None:
    all_passed = True
    for name, fn in CHECKS:
        try:
            fn()
            print(f"[PASS] {name}")
        except AssertionError as e:
            print(f"[FAIL] {name} - {e}")
            all_passed = False
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
