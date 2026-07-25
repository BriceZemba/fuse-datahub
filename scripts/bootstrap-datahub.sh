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
  echo "    GMS did not come up in 10 minutes. Check: docker ps -a" >&2
  return 1
}

existing="$(docker ps -aq --filter 'name=datahub' || true)"

if [ -n "$existing" ]; then
  echo "==> existing DataHub containers found, restarting them"
  docker start $existing >/dev/null
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
