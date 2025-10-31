# Optional: Only needed if you want full control. The devcontainer.json already selects a base image and features.
FROM mcr.microsoft.com/devcontainers/base:jammy

USER root

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       ca-certificates curl git unzip \
       openjdk-8-jdk maven \
       python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20 via NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && node -v && npm -v

# Ensure `python`/`pip` commands exist
RUN ln -sf /usr/bin/python3 /usr/local/bin/python \
    && ln -sf /usr/bin/pip3 /usr/local/bin/pip

# Set JAVA_HOME for JDK 8
ENV JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
ENV PATH="$JAVA_HOME/bin:$PATH"

WORKDIR /workspaces/intention-test-extension

# Copy minimal files for dependency install
COPY --chown=vscode:vscode backend/requirements.txt backend/requirements.txt
COPY --chown=vscode:vscode package.json package-lock.json ./

# Install Python and Node dependencies
RUN pip install -r backend/requirements.txt \
    && npm ci

# Install CodeQL CLI for Linux (to user local bin)
USER vscode
RUN mkdir -p /home/vscode/.local/apps /home/vscode/.local/bin \
    && CODEQL_URL=$(curl -fsSL https://api.github.com/repos/github/codeql-cli-binaries/releases/latest \
         | grep -Eo '"browser_download_url"\s*:\s*"[^"]+linux64\.zip"' | head -n1 | cut -d '"' -f 4) \
    && echo "Download: ${CODEQL_URL}" \
    && curl -fL "$CODEQL_URL" -o /home/vscode/.local/apps/codeql-linux64.zip \
    && unzip -q -o /home/vscode/.local/apps/codeql-linux64.zip -d /home/vscode/.local/apps \
    && rm -f /home/vscode/.local/apps/codeql-linux64.zip \
    && CODEQL_DIR=$(find /home/vscode/.local/apps -maxdepth 1 -type d -name 'codeql*' | head -n1) \
    && ln -sf "$CODEQL_DIR/codeql" /home/vscode/.local/bin/codeql

ENV PATH="/home/vscode/.local/bin:$PATH"

EXPOSE 8080


