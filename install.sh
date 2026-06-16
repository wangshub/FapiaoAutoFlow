#!/usr/bin/env bash
# FapiaoAutoFlow 一键安装:
#   curl -fsSL https://raw.githubusercontent.com/wangshub/FapiaoAutoFlow/main/install.sh | bash
# 克隆项目 → 建虚拟环境装依赖 → 交互式生成配置。可用环境变量 FAPIAO_DIR / PYTHON 覆盖。
set -euo pipefail

REPO="https://github.com/wangshub/FapiaoAutoFlow.git"
DIR="${FAPIAO_DIR:-$HOME/FapiaoAutoFlow}"
PY="${PYTHON:-python3}"

info() { printf "\033[36m▸ %s\033[0m\n" "$*"; }
die()  { printf "\033[31m✗ %s\033[0m\n" "$*" >&2; exit 1; }

command -v git >/dev/null 2>&1 || die "需要 git,请先安装"
command -v "$PY" >/dev/null 2>&1 || die "需要 python3(>=3.9),请先安装"

# 1. 克隆或更新
if [ -d "$DIR/.git" ]; then
  info "更新已有仓库:$DIR"
  git -C "$DIR" pull --ff-only || info "（拉取失败,沿用本地版本）"
else
  info "克隆到:$DIR"
  git clone --depth 1 "$REPO" "$DIR"
fi
cd "$DIR"

# 2. 虚拟环境 + 依赖(国内走阿里云镜像,失败回退默认源)
info "创建虚拟环境并安装依赖（首次较慢）"
"$PY" -m venv .venv
PIP="$DIR/.venv/bin/pip"
"$PIP" install -q --upgrade pip >/dev/null
"$PIP" install -q -e . --index-url https://mirrors.aliyun.com/pypi/simple/ >/dev/null 2>&1 \
  || "$PIP" install -q -e . >/dev/null
# OFD 国标发票支持(依赖较重,装失败不致命——缺它时 OFD 会进待处理)
"$PIP" install -q easyofd --index-url https://mirrors.aliyun.com/pypi/simple/ >/dev/null 2>&1 \
  || info "easyofd 安装失败,OFD 发票将进待处理(可后续手动 pip install easyofd)"

# 3. 配置(curl|bash 时 stdin 是脚本本身,需从 /dev/tty 读取交互输入)
if [ -f config.yaml ]; then
  info "已存在 config.yaml,跳过向导（重配可运行:.venv/bin/fapiao init）"
elif [ -e /dev/tty ]; then
  "$DIR/.venv/bin/fapiao" init < /dev/tty
else
  cp config.example.yaml config.yaml
  info "非交互环境:已生成 config.yaml 模板,请编辑后再运行"
fi

# 4. 完成
printf "\n\033[32m✅ 安装完成\033[0m  目录:%s\n" "$DIR"
cat <<EOF
  立即收取一次:  cd "$DIR" && .venv/bin/fapiao run
  定时(每30分钟):crontab -e 加一行 —— 见 README「定时运行」
  Docker 部署:    cd "$DIR" && docker compose up -d --build
EOF
