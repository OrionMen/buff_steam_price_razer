#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if command -v py >/dev/null 2>&1; then
  PYTHON=(py -3)
elif command -v python >/dev/null 2>&1; then
  PYTHON=(python)
else
  echo "未找到 Python 3。请安装 Python 3.10 或更高版本，并勾选 Add Python to PATH。" >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "未找到 curl。请使用最新版 Git for Windows 自带的 Git Bash。" >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  echo "正在创建 Python 虚拟环境……"
  "${PYTHON[@]}" -m venv .venv
fi

# Git Bash uses the POSIX activation script even though the environment is on Windows.
source .venv/Scripts/activate

echo "正在安装或检查依赖……"
python -m pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo
  echo "已生成 .env。请先填写 BUFF_COOKIE 并把 SCAN_MODE 改为 live，保存后再次运行本脚本。"
  exit 0
fi

echo
echo "饰差雷达正在启动：http://127.0.0.1:5050"
echo "停止服务请按 Ctrl+C。"
python app.py
