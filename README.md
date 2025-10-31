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

### Start up the Python backend

We suggest using **Python 3.10** which has been tested on.
First install the requirements:

```shell
cd backend
pip install -r requirements.txt
```

Modify the `backend/config.ini`:

```ini
[openai]
apikey = your-open-ai-key
url = https://api.openai.com/v1

[tools]
codeql = /Users/<you>/.local/bin/codeql
```

Then start the backend HTTP server:

```shell
# Start on default 8080 port
python server.py

# Start on another port
python server.py --port 12345
```

### Run the extension in debug mode

First install node dependencies from project root:

```shell
npm install
```

Then in Cursor/VS Code, open Command Palette → Start Debugging, select `Run Extension`.

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
