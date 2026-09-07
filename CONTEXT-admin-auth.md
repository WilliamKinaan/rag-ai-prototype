# Context: Admin auth (Cloudflare Access)

_Last updated: 2026-09-07_
**Status: implemented (code side) — Cloudflare dashboard configuration not
yet done.** Until that's done, every admin route fails closed (401) for
everyone, including the two intended admin users — this is expected, not
a bug (see "Fails closed when unconfigured" below).

## What this is

There is no admin *feature* in this app yet — this lays the security
architecture ahead of one: a minimal placeholder `/admin` page and two
representative `/api/admin/*` endpoints, all protected by
[Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/policies/access/),
with authentication/MFA handled entirely by Cloudflare rather than any
custom login system in this app. Real admin features get built on `/admin`
and `/api/admin/*` later; they inherit this protection automatically as
long as they're added the way this doc describes (see "Adding a new admin
route").

The rest of the app (`/`, `/api/query`, `/api/chat`, `/api/legal-review`,
`/api/corpus`, …) is unaffected and stays public.

## 1. How the auth flow works

1. A browser requests `https://rag.williamkinaan.com/admin` (or any
   `/api/admin/*` path). In production this request goes through
   Cloudflare (DNS proxied — see `CONTEXT-deploy-oracle.md`).
2. Cloudflare Access, once an **Application** + **policy** is configured
   for that path (see §5), intercepts the request *before* it reaches
   this app. An unrecognized visitor is redirected to Cloudflare's own
   login page — this is where MFA happens, entirely outside this
   codebase.
3. Once the visitor authenticates and Access's policy allows them,
   Cloudflare forwards the original request on to this app, now carrying
   a **signed JWT** — as the `Cf-Access-Jwt-Assertion` header on every
   forwarded request, and also as a `CF_Authorization` cookie the browser
   holds for its Access session.
4. **This app independently re-verifies that JWT on every privileged
   request** (`webapp/cf_access.py`, `require_admin`) — signature, issuer,
   audience, expiry, then the identity's email against a server-side
   allowlist. It does **not** trust "this request reached me" as proof of
   authorization; step 2 happens at Cloudflare's edge, entirely outside
   this app's control or visibility, so nothing here assumes it happened
   correctly. See §3 for why this matters concretely.

## 2. Which routes/actions are protected

| Route | Method | Guard |
|---|---|---|
| `/admin` | GET | `Depends(cf_access.require_admin)` directly on the route |
| `/api/admin/whoami` | GET | via `admin_router`'s `dependencies=` |
| `/api/admin/ping` | POST | via `admin_router`'s `dependencies=` |

`whoami` and `ping` are placeholders proving the pattern end-to-end (one
read, one privileged/mutating-style call) — not real admin features yet.

**Adding a new admin route**: add it to `admin_router`
(`webapp/app.py`) rather than `app` directly. The router's
`dependencies=[Depends(cf_access.require_admin)]` covers every route
added to it automatically, so a new route can't accidentally ship
unguarded. If an admin route ever needs to live outside that router (e.g.
a new top-level page like `/admin/something`), give it its own
`Depends(cf_access.require_admin)` explicitly — never rely on `/admin`
having been visited first, since API/page routes are directly callable
without it.

Also note: `webapp/admin_static/admin.html` (the file `/admin` serves)
deliberately does **not** live under `webapp/static/`, which is mounted
wholesale and unauthenticated at `/`. Anything meant to be admin-only
must not be placed there, or it becomes reachable by filename with no
check at all.

## 3. How server-side verification is performed

`webapp/cf_access.py`, `require_admin()` — a FastAPI dependency:

1. Reads the JWT from the `Cf-Access-Jwt-Assertion` header (present on
   every request Access actually forwarded), falling back to the
   `CF_Authorization` cookie. Missing → **401**.
2. Verifies the JWT using `PyJWT`'s `PyJWKClient` against Cloudflare's
   published JWKS (`https://<team-domain>/cdn-cgi/access/certs`) —
   signature, and via `jwt.decode(..., audience=..., issuer=...)`: `aud`
   matches one of the configured Access Application tag(s), `iss` matches
   the team domain, and the token isn't expired. Any failure (bad
   signature, wrong `aud`/`iss`, expired, or even a transient JWKS-fetch
   error) → **401**.
3. Checks the token's `email` claim against `ADMIN_ALLOWED_EMAILS` — a
   second, server-side check on top of Cloudflare's own policy, not a
   replacement for it. Not present or not allowlisted → **403**.
4. Only if all of the above pass does the route handler run.

If `CF_ACCESS_TEAM_DOMAIN`/`CF_ACCESS_AUD` aren't set at all, every admin
request gets **401** immediately — see "Fails closed when unconfigured".

**Why this matters even though Cloudflare already enforces this at the
edge**: production also still has a raw-IP path,
`http://134.98.154.12:8000` (documented as open/unproxied in
`CONTEXT-deploy-oracle.md`'s "Known follow-ups"), which bypasses
Cloudflare entirely. Because verification here is cryptographic and
server-side, a request that reaches the app that way still can't get past
`require_admin` — it has no way to produce a validly-signed Cloudflare
token. Firewalling that raw-IP path off is still a good idea as defense
in depth, but this design doesn't depend on it.

## 4. Environment variables / secrets required

Added to `.env.example`; all three are required together — any one
missing means every admin route 401s:

| Variable | What it is | Where it comes from |
|---|---|---|
| `CF_ACCESS_TEAM_DOMAIN` | Zero Trust team domain, no scheme (e.g. `yourteam.cloudflareaccess.com`) | Zero Trust dashboard — shown throughout, e.g. Settings → Custom Pages |
| `CF_ACCESS_AUD` | Comma-separated Access Application "Audience" tag(s) | Access → Applications → (your app) → Overview, after creating it |
| `ADMIN_ALLOWED_EMAILS` | Comma-separated emails of the authorized admins | Whatever emails the two admins actually sign in with |

None of these are secrets in the traditional sense (they're not usable to
authenticate as anyone — they only narrow what an *already-Cloudflare-
verified* token is accepted for), but they still control access, so treat
them with the same care as the other keys already in `.env` (not
committed; see `.env.example`'s existing convention).

## 5. Cloudflare dashboard configuration (to be done by the account owner)

Nothing is configured yet — this needs to happen once, in the Cloudflare
Zero Trust dashboard:

1. **Note the team domain.** Zero Trust → Settings, or any Access page
   shows it, e.g. `yourteam.cloudflareaccess.com`. → `CF_ACCESS_TEAM_DOMAIN`.
2. **Create two Access Applications** (self-hosted), since `/admin*` and
   `/api/admin*` don't share a path prefix:
   - Domain `rag.williamkinaan.com`, path `/admin*`
   - Domain `rag.williamkinaan.com`, path `/api/admin*`

   For each: **Policy** → Action **Allow**, Include → **Emails** → the two
   authorized users' addresses. No other include rule — this is the
   entire authorization surface at the edge.
3. **Copy each Application's AUD tag** (its Overview tab, after saving) —
   put both into `CF_ACCESS_AUD`, comma-separated.
4. **Set the three env vars on the server**, not just locally: SSH in and
   add `CF_ACCESS_TEAM_DOMAIN=`, `CF_ACCESS_AUD=`, `ADMIN_ALLOWED_EMAILS=`
   to `/home/opc/rag-prototype/.env` (that file isn't in the repo — see
   `CONTEXT-deploy-oracle.md`). **`deploy-oracle.sh` does not create or
   touch this file** — it only `git pull`s, installs deps, and restarts —
   so this is a manual, one-time step, needed before or right alongside
   the first deploy that includes this feature. Skipping it leaves admin
   routes 401ing for the real admins too, not just attackers.
5. Restart the service (`sudo systemctl restart rag-prototype`, or just
   let `deploy-oracle.sh` do it) after the `.env` edit so the new values
   are picked up.

**Troubleshooting**: an empty/unset `ADMIN_ALLOWED_EMAILS` means 403 for
*everyone*, including authorized users — that's the fail-closed design,
not a bug; check it's actually set on the server. Cloudflare **service
tokens** (non-interactive, no `email` claim — only `common_name`) will
also 403 here by design; they're not treated as an admin identity.

## 6. Testing: direct calls rejected when unauthenticated

Two different checks, deliberately — going through the protected hostname
only proves Cloudflare's edge is configured; it never reaches this app's
own code at all (Access intercepts first), so it doesn't actually test
the requirement ("every admin API route... verify... directly, without
ever visiting the admin UI"). The origin-direct check below is the one
that does.

**a) Through the hostname, no Cloudflare session** — proves Access itself
is configured on the path:

```bash
curl -i https://rag.williamkinaan.com/api/admin/whoami
```

Expect a **302** redirect to `<team-domain>/cdn-cgi/access/login/...` —
the request never reaches this app; Cloudflare stops it first. A 401/403
here instead would mean the Access Application/policy from §5 isn't
actually attached to this path.

**b) Directly against the origin, bypassing Cloudflare entirely** — this
is the actual test for the requirement: an attacker who knows/discovers
the admin API URL and skips the UI, and in this deploy can also skip
Cloudflare altogether via the documented open raw-IP path
(`CONTEXT-deploy-oracle.md`'s "Known follow-ups"):

```bash
curl -i http://134.98.154.12:8000/admin                 # expect 401
curl -i http://134.98.154.12:8000/api/admin/whoami       # expect 401
curl -i -X POST http://134.98.154.12:8000/api/admin/ping # expect 401
```

(Or run the same curls against `http://localhost:8000/...` from a shell
on the box itself, if the raw-IP port ever gets firewalled off.) Each
must 401 independently — no Cloudflare in front here at all, so this is
what actually proves the app-side guard, not the edge, is what's
rejecting the request.

Also confirmed as part of building this feature, no live Cloudflare
needed: `python webapp/cf_access_selftest.py` exercises the verification
logic itself (signature/`iss`/`aud`/`exp`/allowlist/multi-AUD) against a
throwaway keypair — useful for regression-checking this file after any
future change to it.

## 7. Testing: authenticated but unauthorized is still rejected

This checks that the server-side `ADMIN_ALLOWED_EMAILS` allowlist is a
real, independent check — not just delegating entirely to Cloudflare's
own policy. Do this against the **origin**, not the hostname — going
through Cloudflare with a non-allowlisted email would already get
blocked at the edge (by the Access policy itself), which doesn't prove
this app's own check does anything:

1. In the Cloudflare Access policy (either Application from §5),
   temporarily add a third test email — one **not** in
   `ADMIN_ALLOWED_EMAILS`.
2. Sign in as that user through `https://rag.williamkinaan.com/admin` in
   a browser (passes Cloudflare's own login/MFA — Access's policy allows
   them through to the app).
3. Open devtools → Application/Storage → cookies for
   `rag.williamkinaan.com`, copy the `CF_Authorization` cookie value.
4. Replay it directly against the origin, skipping Cloudflare:
   ```bash
   curl -i -H "Cookie: CF_Authorization=<value>" http://134.98.154.12:8000/api/admin/whoami
   ```
5. Expect **403** — this app's own allowlist check is what's rejecting
   it, not Cloudflare's policy (which already let this token through once
   at the edge).
6. Remove the test email from the Cloudflare policy afterward.
