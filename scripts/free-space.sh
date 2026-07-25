#!/usr/bin/env bash
# Reclaim disk in a codespace without destroying the DataHub catalog.
#
# Deliberately does NOT run `docker system prune --volumes`: DataHub's MySQL and
# Elasticsearch data live in volumes, and wiping them means re-ingesting everything.
set -euo pipefail

echo "==> before"
df -h / | tail -1

docker image prune -f >/dev/null || true
docker builder prune -f >/dev/null || true
pip cache purge >/dev/null 2>&1 || true
uv cache clean >/dev/null 2>&1 || true
sudo apt-get clean >/dev/null 2>&1 || true
rm -rf ~/.cache/ms-playwright ~/.npm/_cacache 2>/dev/null || true

echo "==> after"
df -h / | tail -1

cat <<'EOF'

  Still short on space? In order of preference:
    1. docker container prune -f          # removes stopped non-DataHub containers
    2. docker image prune -af             # removes ALL unused images (DataHub re-pulls)
    3. recreate the codespace on an 8-core machine (64GB disk, but 8 core-hours/hour)

  Never `docker system prune --volumes` while you want to keep the loaded catalog.

EOF
