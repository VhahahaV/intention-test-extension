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

# Ensure JAVA_HOME is set for Java operations
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-8-openjdk-amd64}"
export PATH="${JAVA_HOME}/bin:${PATH}"

# Only overwrite config.ini if OPENAI_API_KEY is provided via environment variable
# Otherwise, use existing config.ini if it exists
if [[ -n "${OPENAI_KEY}" ]]; then
    # Environment variable provided, generate config.ini
    cat > "${CONFIG_FILE}" <<EOF
[openai]
apikey = ${OPENAI_KEY}
url = ${OPENAI_URL}

[tools]
codeql = ${CODEQL_BIN}
EOF
elif [[ ! -f "${CONFIG_FILE}" ]]; then
    # No env var and no existing config, create default (will fail but at least has structure)
    cat > "${CONFIG_FILE}" <<EOF
[openai]
apikey = 
url = ${OPENAI_URL}

[tools]
codeql = ${CODEQL_BIN}
EOF
    echo "[entrypoint] Warning: OPENAI_API_KEY not provided and no existing config.ini found." >&2
else
    # Use existing config.ini, but update codeql path if needed
    if grep -q "^codeql = " "${CONFIG_FILE}"; then
        sed -i "s|^codeql = .*|codeql = ${CODEQL_BIN}|" "${CONFIG_FILE}"
    else
        # Add codeql if missing
        if ! grep -q "^\[tools\]" "${CONFIG_FILE}"; then
            echo "" >> "${CONFIG_FILE}"
            echo "[tools]" >> "${CONFIG_FILE}"
        fi
        echo "codeql = ${CODEQL_BIN}" >> "${CONFIG_FILE}"
    fi
    echo "[entrypoint] Using existing config.ini (OPENAI_API_KEY from file)" >&2
fi

# Verify Java is available
if ! command -v java >/dev/null 2>&1; then
    echo "[entrypoint] Error: Java not found. JAVA_HOME=${JAVA_HOME}" >&2
    exit 1
fi

cd backend
exec python server.py --port "${PORT}"
