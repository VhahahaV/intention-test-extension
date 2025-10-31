# Deploy Guide

本文档记录两种在本地通过容器启动开发环境的方式：Dev Containers（推荐）与原生 Docker CLI。

## 前置条件
- 已安装 Docker Desktop（或其它 Docker 主机）
- 本仓库代码已在本机可访问路径：`/Users/<you>/Code/intention-test-extension`

## 方式一：Dev Containers（推荐）
本仓库已提供 `.devcontainer/` 配置，开箱即用。

1) 在 Cursor/VS Code 打开项目根目录。
2) 打开命令面板（Cmd+Shift+P）→ 执行：`Dev Containers: Reopen in Container`。
3) 首次启动将自动安装：Node 20、Python 3.10、Temurin JDK 8、Maven 3.9，并执行：
   ```bash
   pip install -r backend/requirements.txt && npm ci
   ```
4) 容器内启动后端：
   ```bash
   cd backend
   python server.py  # 默认监听 8080（devcontainer 已转发 8080）
   ```
5) 在宿主侧用 Cursor/VS Code 运行扩展（Run Extension）。如端口非 8080，请在扩展设置中调整 `Intention Test: Port`。

> 说明：如需修改容器规格或工具链版本，可以编辑 `.devcontainer/devcontainer.json`。

## 方式二：Docker CLI（无需 Dev Containers 扩展）
如果不使用 Dev Containers，可直接用 Docker 运行一个临时容器并挂载源码。

```bash
docker run -it --rm \
  -p 8080:8080 \
  -v /Users/<you>/Code/intention-test-extension:/workspaces/intention-test-extension \
  -w /workspaces/intention-test-extension \
  mcr.microsoft.com/devcontainers/base:jammy bash -lc "\
    curl -fsSL https://raw.githubusercontent.com/devcontainers/features/main/script-library/node/install.sh | bash -s -- 20 && \
    curl -fsSL https://raw.githubusercontent.com/devcontainers/features/main/script-library/python/install.sh | bash -s -- 3.10 && \
    curl -fsSL https://raw.githubusercontent.com/devcontainers/features/main/src/java/install.sh | bash -s -- temurin 8 && \
    curl -fsSL https://raw.githubusercontent.com/devcontainers/features/main/src/maven/install.sh | bash -s -- 3.9 && \
    pip install -r backend/requirements.txt && npm ci && \
    cd backend && python server.py"
```

启动成功后端口 8080 将映射到宿主机。宿主侧同样通过 Cursor/VS Code 运行扩展进行联调。

## 环境变量与配置
- OpenAI：编辑 `backend/config.ini`
  ```ini
  [openai]
  apikey = <your-openai-key>
  url = https://api.openai.com/v1

  [tools]
  codeql = /home/vscode/.local/bin/codeql  # 或宿主路径映射后的可执行
  ```
- Java 8：Dev Containers 内已安装 Temurin JDK 8；本地运行时需自行设置 `JAVA_HOME` 与 `PATH`。
- CodeQL：请按 README 的“Environment setup (macOS)”章节准备并写入 PATH；或在容器内按需安装到 `~/.local/bin`。

## 常见问题
- 扩展界面“Waiting for request…”：多为端口不一致或后端未启动；核对端口并重试。
- JSON 错误中包含 `HTTP/1.0 5xx`：查看后端日志，补齐 `config.ini` 或环境变量。
- OpenAI 429（配额不足）：更换有额度的 Key；容器内/宿主侧均可通过更新 `config.ini` 生效。
