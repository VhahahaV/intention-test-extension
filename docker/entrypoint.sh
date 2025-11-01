#!/usr/bin/env bash
set -euo pipefail

cd /app

CONFIG_FILE="backend/config.ini"
APP_USER="${APP_USER:-vscode}"
APP_HOME="${APP_HOME:-/home/${APP_USER}}"
OPENAI_KEY="${OPENAI_API_KEY:-}"
OPENAI_URL="${OPENAI_API_URL:-https://api.openai.com/v1}"
CODEQL_BIN="${CODEQL_PATH:-${APP_HOME}/.local/bin/codeql}"
PORT="${SERVER_PORT:-8080}"

cat > "${CONFIG_FILE}" <<EOF
[openai]
apikey = ${OPENAI_KEY}
url = ${OPENAI_URL}

[tools]
codeql = ${CODEQL_BIN}
EOF
[[ -n "${OPENAI_KEY}" ]] || echo "[entrypoint] Warning: OPENAI_API_KEY is empty; backend will not be able to call OpenAI APIs." >&2

cd backend
exec python server.py --port "${PORT}"
