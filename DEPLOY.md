# Deploy Guide

本文档记录两种在本地通过容器启动开发环境的方式：Dev Containers（推荐）与原生 Docker CLI，并给出更细的操作步骤与排错指南。两种方案共用仓库根目录的 `Dockerfile` 所构建的镜像。

## 前置条件
- 安装并启动 Docker Desktop（或其它 Docker 主机）
- 已克隆本仓库：`/Users/<you>/Code/intention-test-extension`
- 推荐扩展（Cursor/VS Code）：
  - 必装：Dev Containers（ms-vscode-remote.remote-containers）
  - 建议：Docker（ms-azuretools.vscode-docker）、Remote Development Extension Pack（ms-vscode-remote.vscode-remote-extensionpack）

---

## 第一步：构建通用镜像

在仓库根目录执行以下命令构建镜像，供 Dev Containers 与原生 docker 运行复用：

```bash
docker build -t intention-test .
```

- 默认基础镜像为 `mcr.microsoft.com/devcontainers/base:jammy`（国内网络环境相对稳定）。
- 如需更换基础镜像，可添加 `--build-arg BASE_IMAGE=<your-base-image>`（例如 `ubuntu:22.04`）。
- 首次构建需要拉取系统依赖、PyPI 包、npm 包与 CodeQL CLI，耗时较长；后续利用缓存会明显加快。
- 若网络受限，建议预先配置代理或选择镜像源以避免超时。

> VS Code 的 Dev Containers 也会在首次打开仓库时使用同一个 `Dockerfile` 自动构建；提前执行 `docker build` 能减少编辑器等待时间。

---

## 方式一：Dev Containers（推荐，一键容器内开发）

构建完成后，可在 VS Code/Cursor 中通过 Dev Containers 进入容器化开发环境。仓库的 `.devcontainer/devcontainer.json` 已配置使用根目录 Dockerfile，并在容器创建后自动安装依赖。

### A. 启动容器
1) 在 Cursor/VS Code 打开项目根目录。
2) Cmd+Shift+P → 执行：`Dev Containers: Reopen in Container`。
3) 首次进入或选择 `Dev Containers: Rebuild Container` 时会复用你已构建的 `intention-test` 镜像（若本地不存在则自动构建）。
4) 进入容器后会自动执行：
   ```bash
   pip install -r backend/requirements.txt && npm ci
   ```
5) 端口转发：`8080` 已在 devcontainer 中声明为转发。

### B. 配置密钥与工具
1) 编辑容器内 `backend/config.ini`：
   ```ini
   [openai]
   apikey = <your-openai-key>
   url = https://api.openai.com/v1

   [tools]
   codeql = /home/vscode/.local/bin/codeql
   ```
2) 准备 CodeQL（如需）：
   ```bash
   mkdir -p ~/.local/apps ~/.local/bin
   # 将你下载的 codeql-osx64.zip / linux64.zip 拷入容器，或直接在容器内下载对应平台 zip
   unzip -q -o /path/to/codeql-<platform>.zip -d ~/.local/apps
   ln -sf ~/.local/apps/codeql/codeql ~/.local/bin/codeql
   echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
   codeql version
   ```

### C. 启动后端与扩展
1) 容器内启动后端：
   ```bash
   cd backend
   python server.py  # 默认 8080
   ```
2) 宿主侧用 Cursor/VS Code → “Run Extension” 启动扩展。
3) 如端口非 8080，在扩展设置中调整 `Intention Test: Port`。

### D. 最小验证
- 宿主侧验证后端健康：
  ```bash
  curl -s -o /dev/null -w "%{http_code}\n" \
    -H "Content-Type: application/json" \
    -X POST http://127.0.0.1:8080/junitVersion \
    -d '{"data":4}'
  # 期望返回 200
  ```
- 扩展里选择 demo 项目路径：`backend/data/spark`，并粘贴 README 模板的 test_desc。

> 如需修改容器规格（工具版本、端口），可编辑 `.devcontainer/devcontainer.json`。

---

## 方式二：原生 Docker CLI（直接运行后端）

完成镜像构建后，可直接在终端启动容器，适用于部署脚本、CI 或无需 VS Code 的场景。

### A. 启动容器
```bash
docker run -d --name intention-test \
  -p 8080:8080 \
  -e OPENAI_API_KEY="<你的OpenAI Key>" \
  intention-test
```
- 默认端口为 8080，可通过 `-e SERVER_PORT=8090 -p 8090:8090` 覆盖。
- 可选环境变量：
  - `OPENAI_API_URL`（默认 `https://api.openai.com/v1`）
  - `CODEQL_PATH`（默认 `/home/vscode/.local/bin/codeql`）
- 若要将宿主的 `backend/data` 挂载进容器以保留数据，可附加  
  `-v /Users/<you>/Code/intention-test-extension/backend/data:/app/backend/data`.
- 进行代码热更新开发时，可直接挂载整个仓库，覆盖镜像内的快照：
  ```bash
  docker run -d --name intention-test-dev \
    -p 8080:8080 \
    -e OPENAI_API_KEY="your-open-ai-key" \
    -v /Users/<you>/Code/intention-test-extension:/app \
    vhahahav/intention_test:latest
  ```
  这样容器内 `/app` 与宿主保持同步，只需要重启或热加载后端即可看到代码修改。

容器启动后会自动写入 `backend/config.ini` 并运行 `python backend/server.py --port <SERVER_PORT>`。

### B. 运行与调试
- 查看日志：`docker logs -f intention-test`
- 进入交互 Shell：`docker exec -it intention-test /bin/bash`
- 停止/启动：`docker stop intention-test`，`docker start intention-test`
- 如需重新构建并覆盖：`docker rm -f intention-test` → `docker build` → `docker run`

> 想在 VS Code 中调试该容器，可使用 `Dev Containers: Attach to Running Container...` 选择 `intention-test`。

### C. 健康检查
```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Content-Type: application/json" \
  -X POST http://127.0.0.1:8080/junitVersion \
  -d '{"data":4}'
# 期望返回 200
```
随后可在宿主 VS Code/Cursor 运行 “Run Extension”，将 `Intention Test: Port` 设置为上述端口即可。

---

## 推送镜像到 Docker Hub

构建完成并验证通过后，可将镜像推送到 Docker Hub 仓库 `vhahahav/intention_test`。

### 推荐命名与版本策略
- 仓库名保持全小写：`vhahahav/intention_test`
- 采用 [SemVer](https://semver.org/lang/zh-CN/) 版本号，例如 `0.1.0`。当功能或依赖发生变更时递增次版本/补丁号。
- 每次推送同时维护两个标签：
  - 精确版本：`vhahahav/intention_test:0.1.0`
  - 最新稳定：`vhahahav/intention_test:latest`
- 可选附加标签：
  - `vhahahav/intention_test:0.1.0-<git-sha>`（如需追踪具体构建，可使用 `git rev-parse --short HEAD`）
  - `vhahahav/intention_test:dev-<date>`（用于临时测试版，不覆盖正式 `latest`）

### 推送步骤
```bash
# 1) 登录 Docker Hub（首次推送需要）
docker login

# 2) 设置变量便于复用
export IMAGE_LOCAL=intention-test          # 本地构建时使用的标签
export IMAGE_NAME=vhahahav/intention_test  # Docker Hub 仓库
export IMAGE_VERSION=0.1.0                 # 按需更新

# 3) 为镜像打版本标签与 latest 标签
docker tag ${IMAGE_LOCAL} ${IMAGE_NAME}:${IMAGE_VERSION}
docker tag ${IMAGE_LOCAL} ${IMAGE_NAME}:latest

# 4) 推送到远端
docker push ${IMAGE_NAME}:${IMAGE_VERSION}
docker push ${IMAGE_NAME}:latest
```

> 如需额外标签（例如附带 Git 提交号），可重复 `docker tag` 与 `docker push` 步骤。

推送完成后，可在 Docker Hub 仓库的 **Tags** 页面查看版本历史，并将标签同步到部署脚本或 CI/CD 流程。

---

## 环境变量与配置（总结）
- `backend/config.ini`：
  ```ini
  [openai]
  apikey = <your-openai-key>
  url = https://api.openai.com/v1

  [tools]
  codeql = /home/vscode/.local/bin/codeql  # Dev Containers
  ; docker CLI 默认写入同一路径：
  ; codeql = /home/vscode/.local/bin/codeql
  ```
- Java 8：Dev Containers 内已安装；本地运行需设置 `JAVA_HOME` 与 `PATH`。
- CodeQL：建议安装到 `~/.local/bin`，确保 `which codeql` 可找到。

---

## 常见问题与排错
- 扩展显示 “Waiting for request…”：后端未启动或端口不一致。核对 8080 并重试。
- 后端报 500，扩展提示 JSON 含 `HTTP/1.0 5xx`：查看容器内后台日志，补齐 `config.ini`、`codeql` 路径或 `JAVA_HOME`。
- OpenAI 429/配额不足：更换有额度的 Key。后端已做兜底，返回可读错误而非崩溃。
- 缺少 `backend/data/fact_set/...json`：已在代码中降级为空事实/参考，可继续验证；如需完整效果请准备对应数据文件。
- `project_path` 必须指向项目根（如 `backend/data/spark`），不要指到 `src/main/java` 子目录。
- test_desc 必须使用 README 中给出的 3 段模板（# Objective / # Preconditions / # Expected Results）。

---

## 常用命令速查
- 查看容器：`docker ps -a`
- 停止容器：`docker stop <container>`
- 删除容器：`docker rm <container>`
- 查看端口映射：`docker port <container>`
- 进入容器交互：`docker exec -it <container> bash`
