#!/usr/bin/env bash
set -euo pipefail

# 该脚本不替你下载/安装软件本体（按你的要求由读者手工完成），
# 仅做：环境变量配置、CodeQL 解压与软链、项目配置更新，以及必要的提示。

log() { printf "\n[+] %s\n" "$*"; }
warn() { printf "\n[!] %s\n" "$*" >&2; }
die() { printf "\n[x] %s\n" "$*" >&2; exit 1; }

OS="$(uname -s)"
[[ "$OS" == "Darwin" ]] || die "本脚本仅支持 macOS"

# ===================== 使用说明（请先手动完成以下下载/安装） =====================
# 1) Java 8（JDK 1.8）：请到 Oracle 存档页手动下载并安装：
#    https://www.oracle.com/java/technologies/javase/javase8u211-later-archive-downloads.html
# 2) Maven：建议通过 Homebrew 安装（或自行安装），例如：
#    brew install maven
# 3) CodeQL CLI：请从 GitHub Releases 手动下载 macOS osx64 压缩包：
#    https://github.com/github/codeql-cli-binaries/releases/
# ============================================================================

# 可选输入：
#  - JAVA8_HOME 环境变量（如已安装 JDK 1.8，传入其绝对路径以跳过自动探测）
#  - CODEQL_ZIP 指向本地 CodeQL CLI 压缩包（如 ~/Code/codeql-osx64.zip）
#  - CODEQL_DIR 指向已解压的 codeql 目录（如 ~/.local/apps/codeql）

ZSHRC="$HOME/.zshrc"
ZPROFILE="$HOME/.zprofile"

ensure_line_in_file() {
  local file="$1"; shift
  local line="$*"
  grep -qs "^$(printf '%s' "$line" | sed 's/[][^$\*/.]/\\&/g')$" "$file" 2>/dev/null || echo "$line" >> "$file"
}

# ========== 配置 JAVA_HOME 与 PATH（JDK 1.8） ==========
setup_java_env() {
  log "配置 JAVA_HOME（JDK 1.8）与 PATH"
  local java_home="${JAVA8_HOME:-}"
  if [[ -z "${java_home}" ]]; then
    java_home="$((/usr/libexec/java_home -v 1.8) 2>/dev/null || true)"
  fi
  if [[ -z "${java_home}" ]]; then
    warn "未能自动找到 JDK 1.8。请先从 Oracle 页面安装 JDK8 后重试。"
    warn "或以临时方式传入： JAVA8_HOME=/Library/Java/JavaVirtualMachines/jdk1.8.0_xxx.jdk/Contents/Home bash setup/MACOS.sh"
    return 0
  fi

  export JAVA_HOME="$java_home"
  ensure_line_in_file "$ZSHRC" "export JAVA_HOME=\"$JAVA_HOME\""
  ensure_line_in_file "$ZSHRC" "export PATH=\"\$JAVA_HOME/bin:\$PATH\""
  ensure_line_in_file "$ZPROFILE" "export JAVA_HOME=\"$JAVA_HOME\""
  ensure_line_in_file "$ZPROFILE" "export PATH=\"\$JAVA_HOME/bin:\$PATH\""
  log "已写入 JAVA_HOME 到 $ZSHRC 与 $ZPROFILE：$JAVA_HOME"
}

# ========== 处理 CodeQL：解压/软链/写 PATH/更新项目配置 ==========
setup_codeql() {
  log "配置 CodeQL CLI"
  mkdir -p "$HOME/.local/apps" "$HOME/.local/bin"

  local codeql_dir="${CODEQL_DIR:-}"
  local codeql_zip="${CODEQL_ZIP:-}"

  if [[ -z "$codeql_dir" ]]; then
    # 若未指定目录，则尝试使用压缩包解压
    if [[ -z "$codeql_zip" ]]; then
      # 常见默认路径（可根据需要修改）
      if [[ -f "$HOME/Code/codeql-osx64.zip" ]]; then
        codeql_zip="$HOME/Code/codeql-osx64.zip"
      fi
    fi

    if [[ -n "$codeql_zip" && -f "$codeql_zip" ]]; then
      log "解压 CodeQL 压缩包：$codeql_zip"
      unzip -q -o "$codeql_zip" -d "$HOME/.local/apps"
      codeql_dir="$(find "$HOME/.local/apps" -maxdepth 1 -type d -name 'codeql*' | head -n1 || true)"
    else
      warn "未提供 CODEQL_ZIP，且未在默认路径找到压缩包。跳过解压，仅进行 PATH 与配置提示。"
    fi
  fi

  if [[ -n "$codeql_dir" && -d "$codeql_dir" ]]; then
    ln -sf "$codeql_dir/codeql" "$HOME/.local/bin/codeql"
    log "创建软链：$HOME/.local/bin/codeql -> $codeql_dir/codeql"
  else
    warn "未能定位到 codeql 目录。请先从 Releases 下载并解压，然后设置 CODEQL_DIR 再运行本脚本。"
  fi

  ensure_line_in_file "$ZPROFILE" 'export PATH="$HOME/.local/bin:$PATH"'
  export PATH="$HOME/.local/bin:$PATH"

  if command -v codeql >/dev/null 2>&1; then
    log "CodeQL 版本：$(codeql version | head -n1)"
    # 更新项目后端配置
    local cfg="$HOME/Code/intention-test-extension/backend/config.ini"
    if [[ -f "$cfg" ]]; then
      if grep -qs '^codeql\s*=' "$cfg"; then
        /usr/bin/python3 - <<PY
from pathlib import Path
p=Path(r"$cfg")
s=p.read_text()
if 'codeql =' in s:
    import re
    s=re.sub(r'^codeql\s*=.*$', 'codeql = '+r"$HOME"+'/.local/bin/codeql', s, flags=re.M)
else:
    s=s.strip()+"\ncodeql = "+r"$HOME"+'/.local/bin/codeql' +"\n"
p.write_text(s)
print('已更新 backend/config.ini 中的 codeql 路径')
PY
      fi
    fi
  fi
}

# ========== 可选：Maven 提示 ==========
hint_maven() {
  if command -v mvn >/dev/null 2>&1; then
    log "已检测到 Maven：$(mvn -v | head -n1)"
  else
    warn "未检测到 Maven。你可以手动执行： brew install maven"
  fi
}

# ========== 主流程 ==========
log "开始按你的规范进行环境配置（手动下载 + 我来配置环境变量）"
setup_java_env
setup_codeql
hint_maven

log "验证信息（若未显示版本，请按提示完成前置安装后重试）"
echo "JAVA_HOME=${JAVA_HOME:-未设置}"
java -version || true
mvn -v | head -n1 || true
which codeql || true
codeql version || true

log "完成。建议执行： source ~/.zprofile 或重开终端以加载最新 PATH/JAVA_HOME。"
