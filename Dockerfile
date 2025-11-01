ARG BASE_IMAGE=mcr.microsoft.com/devcontainers/base:jammy
FROM ${BASE_IMAGE} AS runtime

ARG USERNAME=vscode
ARG NODE_MAJOR=20
ARG DEBIAN_FRONTEND=noninteractive

ENV TZ=Etc/UTC

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates curl git unzip \
       build-essential \
       openjdk-8-jdk-headless maven \
       python3 python3-venv python3-pip \
       gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js from NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Prepare virtual environment for Python
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv ${VIRTUAL_ENV} \
    && ${VIRTUAL_ENV}/bin/pip install --no-cache-dir --upgrade pip

ENV APP_USER=${USERNAME}
ENV APP_HOME=/home/${APP_USER}
ENV PATH=${VIRTUAL_ENV}/bin:${PATH}
ENV JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
ENV PATH=${JAVA_HOME}/bin:${PATH}

WORKDIR /app

# Install Python dependencies first for better caching
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Install Node dependencies (used for VS Code extension debugging)
COPY package.json package-lock.json ./
RUN npm ci --omit=optional

# Copy source
COPY . .

# Ensure application user owns workspace
RUN chown -R ${APP_USER}:${APP_USER} /app

USER ${APP_USER}

# Install CodeQL CLI under non-root user
ENV PATH=${APP_HOME}/.local/bin:${PATH}
RUN mkdir -p ${APP_HOME}/.local/apps ${APP_HOME}/.local/bin \
    && CODEQL_ZIP_SRC="/app/codeql-linux64.zip" \
    && if [ -f "${CODEQL_ZIP_SRC}" ]; then \
         CODEQL_ZIP="${CODEQL_ZIP_SRC}"; \
       else \
         CODEQL_ZIP="$(mktemp /tmp/codeql-XXXX.zip)" \
           && CODEQL_URL=$(curl -fsSL https://api.github.com/repos/github/codeql-cli-binaries/releases/latest \
                | grep -Eo '"browser_download_url"\\s*:\\s*"[^"]+linux64\\.zip"' | head -n1 | cut -d '"' -f 4) \
           && curl -fL "${CODEQL_URL}" -o "${CODEQL_ZIP}"; \
       fi \
    && unzip -q -o "${CODEQL_ZIP}" -d ${APP_HOME}/.local/apps \
    && CODEQL_DIR=$(find ${APP_HOME}/.local/apps -maxdepth 1 -type d -name 'codeql*' | head -n1) \
    && ln -sf "${CODEQL_DIR}/codeql" ${APP_HOME}/.local/bin/codeql

# Default config values; entrypoint will rewrite the config with env values
ENV OPENAI_API_URL=https://api.openai.com/v1 \
    CODEQL_PATH=${APP_HOME}/.local/bin/codeql \
    SERVER_PORT=8080

USER root
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER ${APP_USER}

EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
