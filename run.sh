#!/bin/bash
# run.sh — 一键执行全流程（抓取 + AI 简报）
# 用法：bash run.sh

set -e  # 遇到错误立即退出

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=============================="
echo "  科技资讯 AI 简报 - 开始运行"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================="

# 激活虚拟环境
if [ -f "venv/Scripts/activate" ]; then
    # Windows (Git Bash)
    source venv/Scripts/activate
elif [ -f "venv/bin/activate" ]; then
    # macOS / Linux
    source venv/bin/activate
else
    echo "错误：未找到虚拟环境，请先运行 python -m venv venv 并安装依赖"
    exit 1
fi

# 执行主程序
PYTHONUTF8=1 python main.py

echo ""
echo "=============================="
echo "  运行完成！"
echo "=============================="
