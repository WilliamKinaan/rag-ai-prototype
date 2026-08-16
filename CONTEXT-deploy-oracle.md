# Context: Deployment on Oracle Cloud Free Tier

_Last updated: 2026-08-11_
**Status: deployed and live.** `http://134.98.154.12:8000` — search, explore,
corpus browser, and chat (Mistral-backed) all working end to end.

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

Two independent layers both had to be opened for port 8000 — missing
either one means "connection refused" from outside despite the app
running fine locally on the box:
- **OS firewall** (`firewalld`, active by default on OL9):
  `sudo firewall-cmd --permanent --add-port=8000/tcp && sudo firewall-cmd --reload`
- **Cloud network** (Oracle Security List on the instance's VCN): an
  ingress rule added via the console — source `0.0.0.0/0`, TCP, destination
  port `8000`.

No TLS/domain set up — the demo is plain HTTP on the raw public IP
(`http://134.98.154.12:8000`), by explicit scope cut (no domain name
available). Revisit if/when the client demo needs `https://`.

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
  A1.Flex (if capacity ever frees up) or accept the demo going down.
- **No TLS/domain** — plain HTTP on the public IP only.
- **No log rotation / monitoring beyond `journalctl`** — fine for a demo,
  would want more for anything longer-lived.
