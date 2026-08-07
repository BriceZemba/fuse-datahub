#!/usr/bin/env bash
# Bring up a full local DataHub and load everything Fuse's demo needs.
# Works the same on a laptop and inside a GitHub Codespace.
#
# Safe to re-run. A codespace that has been stopped and resumed has the containers
# already built but not running: this restarts them instead of calling quickstart,
# which avoids both the multi-GB re-pull and quickstart's 13GB free-disk check.
set -euo pipefail

wait_for_gms() {
  echo "==> waiting for GMS on :8080"
  for _ in $(seq 1 60); do
    if curl -sf http://localhost:8080/health >/dev/null 2>&1; then
      echo "    GMS is up"
      return 0
    fi
    sleep 10
  done
  echo "    GMS did not come up in 10 minutes." >&2
  echo "    Check which container died:  docker ps -a" >&2
  echo "    Then read its log, e.g.:     docker logs --tail 40 \$(docker ps -aq --filter name=gms | head -1)" >&2
  return 1
}

existing="$(docker ps -aq --filter 'name=datahub' || true)"

if [ -n "$existing" ]; then
  # Order matters. GMS gives up and exits(1) if MySQL, OpenSearch and the schema
  # migration are not ready before it starts, so starting everything at once leaves a
  # healthy-looking stack with a dead GMS.
  echo "==> existing DataHub containers found, restarting them in dependency order"

  start_if_present() {
    for name in $(docker ps -aq --filter "name=$1" 2>/dev/null); do
      docker start "$name" >/dev/null 2>&1 || true
    done
  }

  echo "    storage and messaging"
  start_if_present mysql
  start_if_present opensearch
  start_if_present elasticsearch
  start_if_present broker
  start_if_present zookeeper
  sleep 20

  echo "    schema migration"
  start_if_present system-update
  sleep 30

  echo "    gms, frontend and actions"
  docker start $existing >/dev/null 2>&1 || true
else
  echo "==> starting DataHub for the first time (pulls several GB, allow 10-15 minutes)"
  datahub docker quickstart
fi

wait_for_gms

echo "==> pointing the CLI at the local instance"
datahub init --username datahub --password datahub

if [ "${SKIP_DATAPACK:-}" = "1" ]; then
  echo "==> SKIP_DATAPACK=1, leaving the catalog as-is"
else
  echo "==> loading the showcase-ecommerce datapack (~1,049 entities)"
  datahub datapack load showcase-ecommerce
fi

cat <<'EOF'

  DataHub is running.
    UI  : http://localhost:9002   (datahub / datahub)
    GMS : http://localhost:8080   <- this is what Fuse talks to

  Now:
    1. In the UI: avatar -> Settings -> Access Tokens -> Generate new token
    2. Paste it into .env as DATAHUB_GMS_TOKEN=<token>   (cp .env.example .env first)
    3. fuse doctor
    4. python demo/seed_ml_lineage.py     # adds the ML half of the lineage graph
    5. fuse check --repo demo/dbt-shop --diff demo/scenarios/01-drop-column.patch

  After a codespace restart, just re-run this script: it restarts the existing
  containers rather than pulling anything again.

EOF
