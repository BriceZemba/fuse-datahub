#!/usr/bin/env bash
# Runs once when the codespace is created. Keep it fast: DataHub itself is started
# on demand by scripts/bootstrap-datahub.sh, not here, so a rebuild stays cheap.
set -euo pipefail

python -m pip install --upgrade pip wheel setuptools
python -m pip install --upgrade acryl-datahub
python -m pip install -e ".[dev,openrouter]"
curl -LsSf https://astral.sh/uv/install.sh | sh

# Give the user a .env to edit rather than making them find the template.
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example — add your DataHub token and LLM key there."
fi

cat <<'EOF'

  fuse-datahub is installed.

  Next:
    pytest -q                          # 19 tests, no DataHub needed
    fuse replay examples/01-drop-column # offline demo, no DataHub needed
    ./scripts/bootstrap-datahub.sh      # start DataHub + load sample catalog (~10 min)

  Stop the codespace when you are done — it bills against your free core-hours.

EOF
