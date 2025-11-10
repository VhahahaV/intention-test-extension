# Intention Test VS Code Extension

## How to Run

> [!NOTE]
> Intention Test VS Code extension has not implemented one-click running for now.
> A local Python backend should be started before running the extension.

### Prerequisites

Intention Test requires the following development languages:

+ [**Python 3.10+**](https://www.python.org/downloads/) with [**PyTorch**](https://pytorch.org/get-started/locally/)
+ [**Node.js**](https://nodejs.org/en/download/package-manager)

And the following tools for source code analyzation (manual download by user):

+ [**Oracle JDK 1.8**](https://www.oracle.com/java/technologies/javase/javase8u211-later-archive-downloads.html) (set `JAVA_HOME`)
+ [**Apache Maven**](https://maven.apache.org/download.cgi) (or `brew install maven` on macOS)
+ [**CodeQL CLI**](https://github.com/github/codeql-cli-binaries/releases/)

And an [**OpenAI API key**](https://platform.openai.com/docs/guides/production-best-practices/api-keys) to access GPT-4o.

### Environment setup (macOS)
- Configure Java 8
  ```bash
  echo 'export JAVA_HOME=/Library/Java/JavaVirtualMachines/jdk-1.8.jdk/Contents/Home' >> ~/.zshrc
  echo 'export PATH="$JAVA_HOME/bin:$PATH"' >> ~/.zshrc
  source ~/.zshrc
  ```
- Install Maven (user action):
  ```bash
  brew install maven
  ```
- Install CodeQL CLI (user downloads zip, then):
  ```bash
  mkdir -p ~/.local/apps ~/.local/bin
  unzip -q -o ~/Code/codeql-osx64.zip -d ~/.local/apps
  ln -sf ~/.local/apps/codeql/codeql ~/.local/bin/codeql
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zprofile
  source ~/.zprofile
  codeql version
  ```

Note: The repository also provides `setup/MACOS.sh` to help configure environment variables and CodeQL linking (it expects you to download installers yourself first).

### Start the backend via Docker (recommended)

Pull the latest image from Docker Hub and start the container:

```bash
docker pull vhahahav/intention_test:latest
docker run -d --name intention-test \
  -p 8080:8080 \
  -e OPENAI_API_KEY="your-open-ai-key" \
  -e OPENAI_API_URL="https://api.chatanywhere.tech/v1" \
  vhahahav/intention_test:latest
```

**API 端点配置**：
- 默认使用 `https://api.chatanywhere.tech/v1`（国内推荐，延迟更低）
- 国外用户可使用：`https://api.chatanywhere.org/v1`
- 使用官方 OpenAI API：`https://api.openai.com/v1`

The container writes `backend/config.ini` automatically and starts `python server.py --port 8080`.  
To use another port, change the mapping and environment variable:

```bash
docker run -d --name intention-test \
  -p 8090:8090 \
  -e SERVER_PORT=8090 \
  -e OPENAI_API_KEY="your-open-ai-key" \
  vhahahav/intention_test:latest
```

Logs can be tailed with `docker logs -f intention-test`.  
To rebuild locally instead of pulling, follow `DEPLOY.md`.

#### Hot-reload development with volume mount

To develop against the live source tree, bind-mount the repository so container code follows your local changes:

```bash
docker run -d --name intention-test-dev \
  -p 8080:8080 \
  -e OPENAI_API_KEY="your-open-ai-key" \
  -v /path/to/intention-test-extension:/app \
  vhahahav/intention_test:latest
```

- `/app` inside the container mirrors your host repo; edits on the host take effect immediately.
- Ensure the host directory grants read/write permissions to UID/GID `1000:1000` (container user `vscode`).
- If necessary, add `-u $(id -u):$(id -g)` so the container process runs with your host UID/GID.

### Start the backend locally (alternative)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
cp config.ini config.local.ini  # Optional backup
vim config.ini                  # 填写 OPENAI KEY、URL 与 codeql 路径
# config.ini 示例：
# [openai]
# apikey = your-api-key
# url = https://api.chatanywhere.tech/v1  # 或 https://api.chatanywhere.org/v1（国外）
python server.py --port 8080
```

Ensure Java 8, Maven, CodeQL CLI, and PyTorch are installed as listed above.  
When developing outside Docker, update `config.ini` manually and keep the `codeql` path valid.

### Run the extension in debug mode

First install node dependencies from project root:

```shell
npm install
```

Then in Cursor/VS Code, run the extension host:

```bash
# 编译 TypeScript（watch mode）
npm run watch

# 另开终端启动扩展调试
npx vsce package # (可选，仅需一次)
code --extensionDevelopmentPath=$(pwd)
```

或在 VS Code 中按 `F5` / Command Palette → “Debug: Start Debugging” 选择 `Run Extension`。

If you have specify another port when starting backend server,
change the port in **settings of the new Extension Development Host window** via `Intention Test: Port` before generating test cases.

### Use the demo project to try our tool

Now the tool only supports running on the demo project `backend/data/spark` inside this repository. 

```base
mkdir -p backend/data/ && cd backend/data/
git clone git@github.com:perwendel/spark.git
```

### Provide a minimal valid test description (template)
Paste a valid description in the extension panel (required by backend parser):
```text
# Objective
验证 `ClassName.methodName(ParamTypes...)` 在典型输入下的正确行为。

# Preconditions
1. 已创建 `ClassName` 实例为 `obj`。
2. 准备输入参数：`param1 = ...`，`param2 = ...`。
3. （可选）设置必要的配置/上下文。

# Expected Results
1. 调用 `obj.methodName(param1, param2, ...)` 不抛出异常。
2. 返回值满足断言：`...`（如 不为 null / 大于 0 / 含特定字段）。
3. （可选）对象或外部状态变化符合预期：`...`。
```

### Troubleshooting
- If the extension shows “Waiting for request...”, ensure backend is running and port matches `Intention Test: Port`.
- If you see JSON errors with `HTTP/1.0 5xx`, check backend console for missing config (OpenAI url/apikey, CodeQL path, JAVA_HOME).
- If OpenAI API returns 429 (quota), the backend will surface a readable error instead of crashing; update your key/plan to proceed.

## Acknowledgements

+ Test tube icon comes from <https://www.svgrepo.com/svg/525096/test-tube-minimalistic>
