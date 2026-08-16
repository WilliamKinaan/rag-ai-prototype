# Context: Deployment on Oracle Cloud Free Tier

_Last updated: 2026-08-16_
**Status: deployed and live**, reachable two ways:
- `https://rag.williamkinaan.com` — the primary, domain-based URL (HTTPS
  via Cloudflare + nginx, see "Domain + HTTPS" below)
- `http://134.98.154.12:8000` — still works directly too, unproxied

Search, explore, corpus browser, and chat (Mistral-backed) all working
end to end on both.

## Why Oracle, not Hugging Face Spaces

`CONTEXT-webapp.md` had originally planned a Hugging Face Space (Docker SDK)
as the deploy target, but that was never started. The user separately
created an Oracle Cloud "Always Free" account and asked to deploy there
instead — a full VM sidesteps the memory-cap problem that ruled out Netlify
Functions in the first place (see `CONTEXT-webapp.md`'s hosting-decision
note), since the embedding model can just stay resident in a normal
long-running process.

## The instance

- **Shape: `VM.Standard.E5.Flex`, 1 OCPU / 12GB RAM, x86_64.** Not what was
  originally planned — the intent was `VM.Standard.A1.Flex` (Ampere/Arm),
  Oracle's actual **Always Free** compute shape (up to 4 OCPU/24GB). A1
  capacity was unavailable for the whole session ("Out of host capacity"
  in every availability domain tried, then a rate-limit lockout from
  retrying), so the user fell back to `E2.1.Micro` (too little RAM, 1GB)
  and then this E5.Flex, which isn't Always-Free — it's running on the
  account's **30-day/$300 trial credit**, not the permanent free tier.
  **Follow-up needed before the trial runs out**: either keep polling for
  A1 capacity and migrate, or accept this instance stops working once the
  trial ends (explicitly deferred by the user — "let's come to it later").
- **OS: Oracle Linux 9.8** (not Ubuntu as originally suggested — instance
  ended up on Oracle Linux by default through the shape-selection churn).
  User is `opc`, not `ubuntu`.
- **Python 3.12** installed from the OL9 AppStream repo (`dnf install
  python3.12 python3.12-devel`) — matches the version already verified
  locally, so none of `requirements.txt`'s pins needed loosening.
- SSH key: `~/.ssh/oracle_rag_prototype` (ed25519, generated this session,
  private key stays local, not in the repo).

## Two Linux-specific bugs hit and fixed (both now in the repo)

### 1. ChromaDB vs. Oracle Linux's system SQLite

`chromadb` requires SQLite >= 3.35.0; OL9's system SQLite is older, so
`import chromadb` failed immediately with `RuntimeError: Your system has
an unsupported version of sqlite3`. Not a code bug — SQLite is a C library
wrapped by the stdlib `sqlite3` module, and macOS (where this was built
and tested) ships a new-enough one, so this never surfaced locally.

**Fix, applied to the tracked repo (not a server-only hack):**
- `src/sqlite_shim.py` (new) — swaps `sys.modules["sqlite3"]` for
  `pysqlite3` (a self-contained modern SQLite build) if that package is
  installed; silent no-op otherwise.
- `import sqlite_shim` added immediately before `import chromadb` in every
  entrypoint that touches Chroma: `src/ingest.py`, `src/query.py`,
  `src/test.py` (gitignored, so not part of the commit), `webapp/app.py`.
- `requirements.txt`: `pysqlite3-binary>=0.5.0; sys_platform == "linux"` —
  the environment marker keeps this off macOS entirely, where it's both
  unnecessary and (being a source-ish/compiled package) a possible install
  risk not worth taking on a machine that doesn't need it.

**Debugging note for future reference:** while chasing this, an early
`nohup uvicorn ... & disown`-style backgrounded run kept failing with the
pre-fix error even after the fix was deployed and manually verified to
work in a `python -c` one-liner — cause never fully pinned down (possibly
environment differences under detached/`setsid` processes), but running
the same command via a directly-tracked foreground SSH process worked
first try. Not an issue once this moved to `systemd` (below), which sets
up its own clean process environment regardless.

### 2. SELinux blocking `systemd` from executing anything under `/home`

Oracle Linux 9 runs SELinux in `Enforcing` mode. Once the app moved to a
proper `systemd` service (see below), it failed every start with:

```
Failed to locate executable /home/opc/rag-prototype/rag-env/bin/uvicorn: Permission denied
```

despite correct Unix permissions and the exact same binary running fine
when invoked manually. This is the standard SELinux behavior: `systemd`
services run in the `init_t` domain, which is denied exec on files
labeled `user_home_t` (the default label for anything under `/home`),
regardless of `rwx` bits.

**Fix (server-side, not something `requirements.txt`/repo code can
express):**
```bash
sudo dnf install -y policycoreutils-python-utils   # provides semanage
sudo semanage fcontext -a -t bin_t '/home/opc/rag-prototype/rag-env/bin(/.*)?'
sudo restorecon -Rv /home/opc/rag-prototype/rag-env/bin
```
This persistently relabels the venv's `bin/` as `bin_t` (the label normal
system executables carry), which `init_t` is allowed to exec. Needs
re-running (or scripting into a setup script) if the venv is ever
recreated at a different path.

## Redeploying after a code change

No CI/CD — pushing to `main` does **not** auto-deploy, and that's
deliberate, not just an unfinished feature: **always confirm with the user
before running `deploy-oracle.sh` (or otherwise SSHing in to restart the
live service)**, even when a change is already committed and pushed.
Committing/pushing to GitHub is fine to do without asking; deploying the
live instance is a separate, explicitly-confirmed step every time.

To ship a change once confirmed:

```bash
# on your Mac: commit + push as normal
git add -A && git commit -m "..." && git push origin main

# on the server:
ssh -i ~/.ssh/oracle_rag_prototype opc@134.98.154.12
~/rag-prototype/deploy-oracle.sh
```

`deploy-oracle.sh` (repo root) does `git pull` → `pip install` (deps,
always run — cheap no-op if nothing changed) → clears `__pycache__` →
`systemctl restart` → polls `/api/index-stats` until healthy (or times out
and dumps the last 40 log lines). Since a plain `git pull` also picks up
any new/edited files under `data/raw/`, and the app rebuilds its index
from `data/raw/` on every startup, editing the corpus needs no separate
ingest step — just push, pull, restart.

## Running as a service

`systemd` unit at `/etc/systemd/system/rag-prototype.service` (server-only
file, not in the repo — recreate from this if the instance is ever rebuilt):

```ini
[Unit]
Description=RAG Prototype FastAPI webapp
After=network.target

[Service]
Type=simple
User=opc
WorkingDirectory=/home/opc/rag-prototype
Environment="PATH=/home/opc/rag-prototype/rag-env/bin:/usr/bin:/bin"
EnvironmentFile=-/home/opc/rag-prototype/.env
ExecStart=/home/opc/rag-prototype/rag-env/bin/uvicorn webapp.app:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`EnvironmentFile=-/home/opc/rag-prototype/.env` is redundant with `llm.py`'s
own `load_dotenv()` call but harmless (leading `-` makes it optional) —
belt and suspenders for the `MISTRAL_API_KEY`.

Enabled (`systemctl enable`) so it survives reboot; `Restart=on-failure`
so a crash doesn't take the demo down permanently.

**Startup is slow — expect ~2 minutes**, not seconds: `build_index_state()`
(loading `bge-m3` + embedding 80 chunks) is entirely CPU-bound on this
1-OCPU box, confirmed via `ps` showing ~97% CPU the whole time, not a hang.
`uvicorn` won't accept connections until that finishes (FastAPI's startup
event blocks the ASGI lifespan), so a curl/health-check immediately after
`systemctl restart` will just hang until it's ready rather than erroring —
that's expected, not a bug.

Common commands:
```bash
sudo systemctl status rag-prototype     # health check
sudo systemctl restart rag-prototype    # restart, e.g. after a git pull
sudo journalctl -u rag-prototype -f     # live logs
```

## Networking

Two independent layers both had to be opened for every port used —
missing either one means "connection refused" (or, for 443 specifically,
a Cloudflare `523`) from outside despite the app/proxy running fine
locally on the box:
- **OS firewall** (`firewalld`, active by default on OL9):
  `sudo firewall-cmd --permanent --add-port=<port>/tcp && sudo firewall-cmd --reload`
- **Cloud network** (Oracle Security List on the instance's VCN): an
  ingress rule added via the console — source `0.0.0.0/0`, TCP, destination
  port `<port>`.

Ports opened this way on both layers: `8000` (rag-prototype, direct),
`8001` (a separate project sharing this box, `llm-playground` — its own
systemd unit, not part of this repo), `80` and `443` (nginx — see below).

Domain + TLS are now set up (see "Domain + HTTPS" below); the raw-IP URLs
(`http://134.98.154.12:8000`, `:8001`) are left open too, unproxied — not
locked down, just superseded by the domain URLs as the primary way in.

## Domain + HTTPS (nginx reverse proxy + Cloudflare)

_Added 2026-08-16._ The user bought `williamkinaan.com` and wanted two
subdomains routing to the two apps already running on this box.

### DNS (Cloudflare)

Two `A` records, both **Proxied** (orange cloud), both pointing at the
instance's public IP `134.98.154.12` — DNS can't route by port, so both
records point at the same IP and the hostname-based split happens in
nginx, not DNS:
- `rag.williamkinaan.com` → rag-prototype (port 8000)
- `llm.williamkinaan.com` → llm-playground (port 8001)

Domain registration/DNS is managed entirely in the Cloudflare dashboard —
not scriptable from this repo or the instance.

### nginx (reverse proxy, server-side only)

Installed via `sudo dnf install -y nginx`. Config at
`/etc/nginx/conf.d/subdomains.conf` (server-only file, not in the repo —
recreate from this if the instance is ever rebuilt):

```nginx
server {
    listen 80;
    server_name rag.williamkinaan.com;
    return 301 https://$host$request_uri;
}

server {
    listen 80;
    server_name llm.williamkinaan.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name rag.williamkinaan.com;

    ssl_certificate     /etc/nginx/ssl/cf-origin.pem;
    ssl_certificate_key /etc/nginx/ssl/cf-origin.key;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 443 ssl;
    server_name llm.williamkinaan.com;

    ssl_certificate     /etc/nginx/ssl/cf-origin.pem;
    ssl_certificate_key /etc/nginx/ssl/cf-origin.key;

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

`sudo systemctl enable --now nginx` so it survives reboot.

### TLS: Cloudflare Origin Certificate

Used a **Cloudflare Origin Certificate** rather than Let's
Encrypt/certbot — free, 15-year validity, one cert covers both
subdomains via a `*.williamkinaan.com` SAN. Generated once in the
Cloudflare dashboard: **SSL/TLS → Origin Server → Create Certificate**
(defaults: Cloudflare generates the key, RSA 2048, hostnames
`*.williamkinaan.com` + `williamkinaan.com`).

Installed on the instance at `/etc/nginx/ssl/cf-origin.pem` (644) and
`/etc/nginx/ssl/cf-origin.key` (600, root-owned) — **server-only, not in
the repo, not escrowed anywhere else**. Cloudflare shows the private key
only once, at creation time; if it's ever lost, the fix is to revoke and
generate a new Origin Certificate in the dashboard and reinstall, not to
try to recover the old one.

Cloudflare's SSL/TLS mode (**SSL/TLS → Overview**, applies to the whole
zone) is set to **Full (strict)** — Cloudflare validates this cert when
connecting to the origin. It started on plain `Full` with no origin cert
installed yet, which made `https://` requests hang/timeout rather than
fail fast — worth knowing if this ever needs debugging again:
`Full`/`Full (strict)` pointed at an origin with no working cert doesn't
error quickly, it just hangs until the client times out.

### SELinux (OL9, Enforcing) — two more relabels needed

Same class of issue as the venv `bin_t` fix earlier in this doc:
- nginx needs the `httpd_can_network_connect` boolean to be allowed to
  `proxy_pass` to `127.0.0.1:8000`/`:8001` at all:
  ```bash
  sudo setsebool -P httpd_can_network_connect on
  ```
- The cert files, after being copied in via `/tmp`, inherited the
  `user_tmp_t` label and nginx failed to read them (`cannot load
  certificate ...: BIO_new_file() failed ... Permission denied`) until
  relabeled to `cert_t`:
  ```bash
  sudo semanage fcontext -a -t cert_t '/etc/nginx/ssl(/.*)?'
  sudo restorecon -Rv /etc/nginx/ssl
  ```

### Firewall / Security List

Same two-layer requirement as port 8000 (see "Networking" above),
applied to `80` and `443`:
```bash
sudo firewall-cmd --permanent --add-port=80/tcp
sudo firewall-cmd --permanent --add-port=443/tcp
sudo firewall-cmd --reload
```
+ matching ingress rules (`0.0.0.0/0`, TCP, ports `80` and `443`) added
in the OCI console.

**Debugging note:** the firewalld commands above were originally chained
after `sudo systemctl reload nginx` in one `set -e` script; the reload
failed on the first attempt (the cert SELinux issue, above), which
aborted the script before the firewalld lines ran. Net effect: nginx was
listening on 443 and everything looked right when tested locally on the
box, but Cloudflare reported `523 origin unreachable` from outside until
this was caught and the firewalld commands re-run standalone. Lesson: a
`set -e` script that aborts partway through doesn't mean everything
*before* the failure point is the only thing that's missing — re-verify
each layer independently rather than assuming the rest of the script ran.

## Deploy-from-scratch steps (for rebuilding on a fresh instance)

```bash
sudo dnf install -y python3.12 python3.12-pip python3.12-devel git gcc gcc-c++ make policycoreutils-python-utils
git clone https://github.com/WilliamKinaan/rag-ai-prototype.git ~/rag-prototype
cd ~/rag-prototype
python3.12 -m venv rag-env
source rag-env/bin/activate
pip install --upgrade pip
pip install -r requirements.txt -r webapp/requirements.txt
# swap in the CPU-only torch build to avoid ~2-3GB of unused CUDA wheels:
pip uninstall -y torch nvidia-cublas-cu12 nvidia-cuda-cupti-cu12 nvidia-cuda-nvrtc-cu12 \
  nvidia-cuda-runtime-cu12 nvidia-cudnn-cu12 nvidia-cufft-cu12 nvidia-curand-cu12 \
  nvidia-cusolver-cu12 nvidia-cusparse-cu12 nvidia-nccl-cu12 nvidia-nvjitlink-cu12 nvidia-nvtx-cu12
pip install torch==2.2.2 --index-url https://download.pytorch.org/whl/cpu

sudo semanage fcontext -a -t bin_t '/home/opc/rag-prototype/rag-env/bin(/.*)?'
sudo restorecon -Rv /home/opc/rag-prototype/rag-env/bin

echo "MISTRAL_API_KEY=..." > ~/rag-prototype/.env
chmod 600 ~/rag-prototype/.env

# create /etc/systemd/system/rag-prototype.service (see above), then:
sudo systemctl daemon-reload
sudo systemctl enable --now rag-prototype

sudo firewall-cmd --permanent --add-port=8000/tcp && sudo firewall-cmd --reload
# + add the Security List ingress rule in the Oracle console (see above)
```

## Known follow-ups (not yet done)

- **Trial-credit expiry** — explicitly deferred by the user. This instance
  isn't Always-Free; decide before the trial ends whether to migrate to
  A1.Flex (if capacity ever frees up) or accept the demo going down. Note
  this now also takes down `llm-playground` and breaks both Cloudflare
  DNS records (they'd need re-pointing at the new IP) if it migrates.
- **Raw-IP + port access left open** — `http://134.98.154.12:8000` and
  `:8001` still work directly, unproxied, alongside the new HTTPS domain
  URLs. Not locked down; fine for a demo.
- **No log rotation / monitoring beyond `journalctl`** — fine for a demo,
  would want more for anything longer-lived.
