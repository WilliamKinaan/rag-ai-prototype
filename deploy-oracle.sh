#!/usr/bin/env bash
# Pull the latest code, reinstall dependencies, restart the systemd service,
# and wait for it to come back up healthy.
#
# Run this ON the Oracle instance (not locally) — SSH in first:
#   ssh -i ~/.ssh/oracle_rag_prototype opc@134.98.154.12
#   ~/rag-prototype/deploy-oracle.sh
#
# See CONTEXT-deploy-oracle.md for the full deployment writeup (instance
# setup, the sqlite/SELinux fixes, systemd unit, networking).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

echo "==> Pulling latest code..."
git pull

echo "==> Installing/updating dependencies..."
source rag-env/bin/activate
pip install -q -r requirements.txt -r webapp/requirements.txt

echo "==> Clearing stale bytecode cache..."
find . -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

echo "==> Restarting service..."
sudo systemctl restart rag-prototype

echo "==> Waiting for it to come back up (model reload takes ~2 min on this box)..."
for i in $(seq 1 30); do
  if curl -sf --max-time 3 localhost/api/index-stats >/dev/null 2>&1; then
    echo "==> READY after $((i * 10))s"
    curl -s localhost/api/index-stats
    echo
    exit 0
  fi
  sleep 10
done

echo "==> TIMED OUT waiting for the service to come up. Recent logs:"
sudo journalctl -u rag-prototype -n 40 --no-pager
exit 1
