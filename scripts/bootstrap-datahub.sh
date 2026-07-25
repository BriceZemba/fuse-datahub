#!/usr/bin/env bash
# Bring up a full local DataHub and load everything Fuse's demo needs.
# Works the same on a laptop and inside a GitHub Codespace.
set -euo pipefail

echo "==> starting DataHub (first run pulls several GB, allow 10-15 minutes)"
datahub docker quickstart

echo "==> waiting for GMS on :8080"
for _ in $(seq 1 60); do
  if curl -sf http://localhost:8080/health >/dev/null 2>&1; then
    echo "    GMS is up"
    break
  fi
  sleep 10
done

echo "==> pointing the CLI at the local instance"
datahub init --username datahub --password datahub

echo "==> loading the showcase-ecommerce datapack (~1,049 entities)"
datahub datapack load showcase-ecommerce

cat <<'EOF'

  DataHub is running.
    UI  : http://localhost:9002   (datahub / datahub)
    GMS : http://localhost:8080   <- this is what Fuse talks to

  Now:
    1. In the UI: avatar -> Settings -> Access Tokens -> Generate new token
    2. echo "DATAHUB_GMS_TOKEN=<token>" >> .env
    3. fuse doctor
    4. python demo/seed_ml_lineage.py     # adds the ML half of the lineage graph
    5. fuse check --repo demo/dbt-shop --diff demo/scenarios/01-drop-column.patch

EOF
